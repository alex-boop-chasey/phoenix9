"""A small TOML writer for the files Phoenix writes (the standard library only reads TOML)."""
import math
import re
from pathlib import Path

from phoenix9 import atomic

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r", "\b": "\\b", "\f": "\\f"}


def _string(text: str) -> str:
    """Return text as a quoted TOML string with everything unsafe escaped."""
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _key(key: object) -> str:
    """Return a table or value key, quoted when it is not safe bare."""
    if not isinstance(key, str):
        raise TypeError(f"TOML keys must be text, not {type(key).__name__}: {key!r}")
    return key if _BARE_KEY.match(key) else _string(key)


def _scalar(value: object, where: str) -> str:
    """Return one scalar value (string, bool, int, float) as TOML text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    raise TypeError(f"Cannot write {type(value).__name__} value at {where}; "
                    "only text, numbers, true/false, lists, and tables are supported")


def _value(value: object, where: str) -> str:
    """Return a scalar or a list of scalars as TOML text."""
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, (list, tuple, dict)):
                raise TypeError(f"Cannot write nested lists or tables inside a list at {where}")
        return "[" + ", ".join(_scalar(item, where) for item in value) + "]"
    return _scalar(value, where)


def _is_table_array(value: object) -> bool:
    """True for a non-empty list made only of dicts; raises if dicts are mixed with other things."""
    if not isinstance(value, (list, tuple)) or not value:
        return False
    dicts = [isinstance(item, dict) for item in value]
    if all(dicts):
        return True
    if any(dicts):
        raise TypeError("Cannot write a list that mixes tables with other values")
    return False


def _ordered(keys: list, key_order: list[str] | None) -> list:
    """Sort keys: those named in key_order first (in that order), then the rest alphabetically."""
    order = key_order or []
    first = [k for k in order if k in keys]
    rest = sorted((k for k in keys if k not in first), key=str)
    return first + rest


def _write_table(lines: list[str], table: dict, path: list[str], key_order: list[str] | None) -> None:
    """Write one table body (scalars first), then its sub-tables and arrays of tables."""
    keys = _ordered(list(table), key_order)
    for k in keys:
        v = table[k]
        if not isinstance(v, dict) and not _is_table_array(v):
            lines.append(f"{_key(k)} = {_value(v, '.'.join(path + [str(k)]))}")
    for k in keys:
        v = table[k]
        sub = path + [_key(k)]
        if isinstance(v, dict):
            if lines:
                lines.append("")
            lines.append("[" + ".".join(sub) + "]")
            _write_table(lines, v, sub, key_order)
        elif _is_table_array(v):
            for item in v:
                if lines:
                    lines.append("")
                lines.append("[[" + ".".join(sub) + "]]")
                _write_table(lines, item, sub, key_order)


def dumps(data: dict, *, header: str = "", key_order: list[str] | None = None) -> str:
    """Return data as TOML text, with optional comment header lines and preferred key order."""
    if not isinstance(data, dict):
        raise TypeError("TOML documents must be a dict at the top level")
    lines = [f"# {line}".rstrip() for line in header.splitlines()]
    if lines:
        lines.append("")
    _write_table(lines, data, [], key_order)
    return "\n".join(lines) + "\n"


def dump(path, data: dict, **kw) -> None:
    """Write data as TOML to path atomically (same options as dumps)."""
    atomic.write_text(Path(path), dumps(data, **kw))
