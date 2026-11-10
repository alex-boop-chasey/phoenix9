"""Read the agent's TOML settings file into a typed object with safe defaults."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

UNCHECKED = "CHECK BEFORE USE"
PRICE_KEYS = ("input_per_mtok", "output_per_mtok", "cache_read_per_mtok", "cache_write_per_mtok")
PRICES_NOT_READY = (
    "The agent's price list hasn't been checked yet, so it won't start. "
    "Fill in the prices in the agent settings file."
)


class ConfigError(Exception):
    """The settings file is wrong, with a plain-English message."""


def _default_prices() -> dict[str, dict[str, object]]:
    return {"claude-sonnet-5-5": {k: UNCHECKED for k in PRICE_KEYS}}


@dataclass
class Config:
    """All agent settings, with defaults for anything not in the file."""

    pack: str = "phoenix"
    model: str = "claude-sonnet-5-5"
    monthly_cap_usd: float = 95.00
    prices: dict[str, dict[str, object]] = field(default_factory=_default_prices)
    api_key_file: str = "/var/lib/phoenix9/agentkit/api-key"
    token_file: str = "/var/lib/phoenix9/agentkit/token"
    db_file: str = "/var/lib/phoenix9/agentkit/agentkit.db"
    host: str = "127.0.0.1"
    port: int = 8097
    phoenix_api: str = "http://127.0.0.1:8095"
    link_schemes: list[str] = field(default_factory=lambda: ["claude"])

    def prices_ready(self) -> bool:
        """True only when every price for the model in use is a real number."""
        table = self.prices.get(self.model)
        if not table:
            return False
        return all(_is_number(table.get(k)) for k in PRICE_KEYS)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_prices(raw: object) -> dict[str, dict[str, object]]:
    if not isinstance(raw, dict):
        raise ConfigError("The setting 'prices' must be a table of models.")
    out: dict[str, dict[str, object]] = {}
    for model, table in raw.items():
        if not isinstance(table, dict):
            raise ConfigError(f"The prices for '{model}' must be a table.")
        for key in table:
            if key not in PRICE_KEYS:
                raise ConfigError(f"Unknown price setting '{key}' for '{model}'.")
        out[model] = dict(table)
    return out


def _check_type(name: str, value: object, want: type) -> None:
    ok = _is_number(value) if want is float else isinstance(value, want) and not (
        want is int and isinstance(value, bool))
    if not ok:
        raise ConfigError(f"The setting '{name}' has the wrong kind of value.")


def from_dict(data: dict) -> Config:
    """Build a Config from parsed TOML, refusing unknown keys."""
    cfg = Config()
    known = {f for f in cfg.__dataclass_fields__}
    for key in data:
        if key not in known:
            raise ConfigError(f"Unknown setting '{key}' in the agent settings file.")
    for key, value in data.items():
        if key == "prices":
            cfg.prices = _check_prices(value)
            continue
        default = getattr(cfg, key)
        if isinstance(default, list):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ConfigError(f"The setting '{key}' must be a list of words.")
        else:
            _check_type(key, value, type(default))
        setattr(cfg, key, float(value) if isinstance(default, float) else value)
    return cfg


def load(path: str | Path) -> Config:
    """Read a config file; a missing file gives the defaults."""
    p = Path(path)
    if not p.exists():
        return Config()
    try:
        data = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"The agent settings file can't be read: {e}") from e
    return from_dict(data)
