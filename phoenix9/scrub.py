"""Secret scrubbing: replace known secret values with [secret] before anything is written to a log."""
import json
from pathlib import Path

MIN_SECRET_LEN = 8
MASK = "[secret]"


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
        return s

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
