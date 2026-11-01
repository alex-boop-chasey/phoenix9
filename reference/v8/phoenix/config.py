"""Where Phoenix keeps its folders, and the settings in phoenix.toml."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULTS: dict[str, object] = {
    "max_tries": 3,
    "builder_timeout_min": 90,
    "checker_timeout_min": 20,
    "check_writer_timeout_min": 20,
    "no_output_timeout_min": 15,
    "usage_probe_min": 30,
    "usage_max_wait_h": 12,
    "container_memory": "4g",
    "container_cpus": 1.5,
    "container_pids": 512,
    "image": "phoenix-step:0.6.0",
    "telegram_script": "",
    "subprocess_env_scrub": False,   # see BUILD-NOTES Step 4: True breaks every Bash call in the step container
}


class ConfigError(Exception):
    """phoenix.toml has a problem. The message says what, in plain English."""


@dataclass(frozen=True)
class Paths:
    """The folders Phoenix uses, all inside PHOENIX_HOME."""

    home: Path
    plans: Path
    runs: Path
    config: Path
    cache: Path

    def all(self) -> dict[str, Path]:
        """Return the folders as a name -> path mapping, in a fixed order."""
        return {"home": self.home, "plans": self.plans, "runs": self.runs,
                "config": self.config, "cache": self.cache}

    def create(self) -> None:
        """Make every folder if it does not exist yet."""
        for path in self.all().values():
            path.mkdir(parents=True, exist_ok=True)


def phoenix_home() -> Path:
    """Return PHOENIX_HOME as an absolute path (default: ./var)."""
    return Path(os.environ.get("PHOENIX_HOME") or "./var").resolve()


def paths() -> Paths:
    """Return the Phoenix folders for the current PHOENIX_HOME (does not create them)."""
    home = phoenix_home()
    return Paths(home=home, plans=home / "plans", runs=home / "runs",
                 config=home / "config", cache=home / "cache")


def _toml_path() -> Path:
    """Return the location of phoenix.toml (inside the config folder)."""
    return paths().config / "phoenix.toml"


def _check_type(key: str, value: object) -> None:
    """Fail in plain English if a setting has the wrong kind of value."""
    default = DEFAULTS[key]
    if isinstance(default, bool) or isinstance(value, bool):
        ok = type(value) is type(default)
    elif isinstance(default, float):
        ok = isinstance(value, (int, float))
    else:
        ok = isinstance(value, type(default))
    if not ok:
        kind = {int: "a whole number", float: "a number", str: "text in quotes"}[type(default)]
        raise ConfigError(f"Setting '{key}' in phoenix.toml should be {kind}, but it is {value!r}.")


def load(path: Path | None = None) -> dict[str, object]:
    """Read phoenix.toml and return all settings, filling in defaults.

    A missing file means all defaults. An unknown setting name, a wrong
    kind of value, or broken TOML raises ConfigError with a readable message.
    """
    path = path or _toml_path()
    settings = dict(DEFAULTS)
    if not path.exists():
        return settings
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from None
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        names = ", ".join(f"'{k}'" for k in unknown)
        known = ", ".join(DEFAULTS)
        raise ConfigError(
            f"{path} has setting(s) Phoenix does not know: {names}. "
            f"Check the spelling. Known settings are: {known}."
        )
    for key, value in data.items():
        _check_type(key, value)
        settings[key] = float(value) if isinstance(DEFAULTS[key], float) else value
    return settings
