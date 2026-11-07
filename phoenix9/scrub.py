"""Secret scrubbing: replace known secret values with [secret] before anything is written to a log.

Besides the values it was told about, the scrubber masks the shapes of common secrets nobody registered:
Anthropic keys (sk-ant-...), GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_..., github_pat_...), PEM private key
blocks (also a block's tail without its BEGIN line), and NAME=value where the name says KEY, TOKEN, SECRET
or PASSWORD."""
import json
import re
from pathlib import Path

MIN_SECRET_LEN = 8
MASK = "[secret]"
PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"), MASK),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), MASK),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{20,}"), MASK),
]
PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
B64_LINE = re.compile(r"[ \t]*[A-Za-z0-9+/=]{16,}[ \t]*\r?")
# NAME=value, NAME: value: the name (at most 80 characters, starting where a word starts) is checked in Python
# so the pattern never backtracks over long runs of text.
ASSIGN = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]{0,80})([ \t]*[=:][ \t]*)([\"']?)"
                    r"([A-Za-z0-9_+/.~-][^\s\"';&|()]{5,})")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD", re.I)


def _assign(m) -> str:
    name, sep, quote, value = m.groups()
    if not SECRET_NAME.search(name) or value.startswith(MASK):
        return m.group(0)
    return name + sep + quote + MASK


def _pem_tails(s: str) -> str:
    """Mask the base64 lines just above each END PRIVATE KEY line (a key's tail without its BEGIN line)."""
    out, pos = [], 0
    for m in PEM_END.finditer(s):
        start = m.start()
        while True:                       # walk back one whole line at a time while it looks like base64
            prev_end = s.rfind("\n", 0, start)
            if prev_end < 0:
                break
            line_start = s.rfind("\n", 0, prev_end) + 1
            if line_start < pos or not B64_LINE.fullmatch(s, line_start, prev_end):
                break
            start = line_start
        if start < m.start():
            out.append(s[pos:start])
            out.append(MASK)
            pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def mask_patterns(s: str) -> str:
    """Mask the secret shapes: known token prefixes, PEM private keys (and their tails), NAME=value assignments."""
    for rx, repl in PATTERNS:
        s = rx.sub(repl, s)
    s = _pem_tails(s)
    return ASSIGN.sub(_assign, s)


class Scrubber:
    """Holds secret values and removes them from text."""

    def __init__(self, secrets: list[str] | None = None):
        """Start with the given secret values (short ones are ignored)."""
        self._secrets: list[str] = []
        self.add(secrets or [])

    def add(self, values) -> None:
        """Add more secret values; values under 8 characters are ignored."""
        for value in values:
            if not isinstance(value, str) or len(value) < MIN_SECRET_LEN:
                continue
            for form in (value, json.dumps(value)[1:-1]):   # also the form seen inside JSON text
                if form not in self._secrets:
                    self._secrets.append(form)
        self._secrets.sort(key=len, reverse=True)

    def values(self) -> list[str]:
        """The secret values held (longest first, JSON-escaped forms included)."""
        return list(self._secrets)

    def text(self, s: str) -> str:
        """Return the text with every known secret replaced by [secret], longest first."""
        for secret in self._secrets:
            s = s.replace(secret, MASK)
        return mask_patterns(s)

    @classmethod
    def from_env_files(cls, paths) -> "Scrubber":
        """Build a scrubber from the values in KEY=VALUE env files (missing files are skipped)."""
        return cls(secrets_from(paths))


def read_env_file(path) -> dict[str, str]:
    """Read KEY=VALUE lines from an env file (blank lines and # comments skipped)."""
    # ported from reference/v8/phoenix/claude.py:227
    values: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def secrets_from(paths) -> list[str]:
    """Return the values in the env files (8+ characters), longest first."""
    # ported from reference/v8/phoenix/claude.py:243
    found: set[str] = set()
    for path in paths:
        if not Path(path).is_file():
            continue
        found.update(v for v in read_env_file(path).values() if len(v) >= MIN_SECRET_LEN)
    return sorted(found, key=len, reverse=True)


_GLOBAL = Scrubber()


def add_secrets(values) -> None:
    """Add secret values to the process-wide scrubber used by every log writer."""
    _GLOBAL.add(values)


def scrub(s: str) -> str:
    """Scrub the text with the process-wide scrubber (call this in every log writer)."""
    return _GLOBAL.text(s)


def known_secrets() -> list[str]:
    """The secret values the process-wide scrubber knows (for the Secret scan; never log them)."""
    return _GLOBAL.values()
