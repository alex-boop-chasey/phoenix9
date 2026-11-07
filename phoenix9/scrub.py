"""Secret scrubbing: replace known secret values with [secret] before anything is written to a log.

Besides the values it was told about, the scrubber masks the shapes of common secrets nobody registered:
Anthropic keys (sk-ant-...), GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_..., github_pat_...), PEM private key
blocks (also a block's tail without its BEGIN line), and NAME=value where a part of the name (split on _ - .
and case changes) is KEY, TOKEN, SECRET or PASSWORD: API_KEY and apiKey are masked, monkey and keyboard are not.
Python exception names (KeyError: 'X', TokenError, PasswordWarning) and traceback lines (`  File "...", line N`
and the source line under it) are never read as NAME: value settings; known values and token shapes still are."""
import bisect
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
# The name's parts: split on _ - . and at case changes (apiKey, APIKey) and digits. Each piece is a plain run, so
# this stays linear; names are at most 81 characters anyway.
NAME_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# KeyError, TokenError, PasswordWarning, json.decoder.SomeException: exception names, never secret names
EXCEPTION_NAME = re.compile(r"(?:Error|Exception|Warning)\Z")
# a traceback frame line and the source line printed under it (one pass over the text, no backtracking)
TRACEBACK_FRAME = re.compile(r'^[ \t]*File "[^"\n]*", line \d+[^\n]*(?:\n(?![ \t]*File ")[ \t]+[^\n]*)?', re.M)
SECRET_WORDS = frozenset({"key", "keys", "token", "tokens", "secret", "secrets", "password", "passwords",
                          "passwd", "pwd"})
# names written as one lower-case word that still say "secret" (apikey, accesstoken, ...)
SECRET_COMPOUNDS = frozenset({"apikey", "apikeys", "accesskey", "secretkey", "privatekey", "authtoken",
                              "accesstoken", "refreshtoken", "apitoken", "apisecret", "clientsecret"})


def name_parts(name: str) -> list[str]:
    """The lower-case parts of a NAME: AWS_SECRET-access.Key -> aws, secret, access, key; myAPIKey2 -> my, api, key, 2."""
    return [p.lower() for p in NAME_PART.findall(name)]


def secret_name(name: str) -> bool:
    """True when one part of the name is a secret word (API_KEY, apiKey, db-password; not monkey or keyboard)."""
    parts = name_parts(name)
    return any(p in SECRET_WORDS or p in SECRET_COMPOUNDS for p in parts)


def _assign(m) -> str:
    name, sep, quote, value = m.groups()
    if not secret_name(name) or EXCEPTION_NAME.search(name) or value.startswith(MASK):
        return m.group(0)
    return name + sep + quote + MASK


def _mask_assignments(s: str) -> str:
    """NAME=value / NAME: value masking, skipping traceback frame lines and their source lines."""
    spans = [(m.start(), m.end()) for m in TRACEBACK_FRAME.finditer(s)] if 'File "' in s else []
    if not spans:
        return ASSIGN.sub(_assign, s)
    starts = [a for a, _ in spans]

    def outside(m) -> str:
        i = bisect.bisect_right(starts, m.start()) - 1
        if i >= 0 and m.start() < spans[i][1]:
            return m.group(0)
        return _assign(m)
    return ASSIGN.sub(outside, s)


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
    return _mask_assignments(s)


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
