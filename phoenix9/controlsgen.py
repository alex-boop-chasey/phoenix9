"""Writes the agent's controls description file (controls.json) from the controls registry."""
import importlib
from pathlib import Path

from phoenix9 import atomic
from phoenix9.ops.controls import CONTROLS, Control, Input

PATH = Path(__file__).resolve().parent.parent / "agentkit" / "agentkit" / "packs" / "phoenix" / "controls.json"


def _first_line(text: str | None) -> str:
    """The first non-empty line of a docstring."""
    for line in (text or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _description(c: Control) -> str:
    """The registry text, else the first docstring line of the ops function, else the reason."""
    if c.text:
        return c.text
    if c.ops:
        module, function = c.ops.split(".")
        doc = _first_line(getattr(importlib.import_module(f"phoenix9.ops.{module}"), function).__doc__)
        if doc:
            return doc
    return c.why


def _input(i: Input) -> dict:
    """One input as plain data."""
    return {"name": i.name, "type": i.type, "required": i.required, "description": i.description,
            "choices": list(i.choices), "where": i.where, "into": list(i.into)}


def _entry(c: Control) -> dict:
    """One control as plain data."""
    return {"name": c.name, "description": _description(c), "inputs": [_input(i) for i in c.inputs],
            "risk": c.risk, "agent": c.agent, "why": c.why, "method": c.method, "route": c.route,
            "fixed": dict(c.fixed), "fixed_query": dict(c.fixed_query), "card": c.card,
            "confirm_with": c.confirm_with, "timeout_s": c.timeout_s}


def describe() -> list[dict]:
    """The JSON-ready list of every control, sorted by name."""
    return sorted((_entry(c) for c in CONTROLS), key=lambda e: e["name"])


def write(path: Path | None = None) -> Path:
    """Write the description file (default: the Phoenix pack's controls.json) and return its path."""
    path = Path(path or PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, describe())
    return path
