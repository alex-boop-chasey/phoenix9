"""Guided-flow state: checks a flow's step record and makes the card data; the state lives in the event log."""
from typing import Any

STATUSES = ("active", "done", "cancelled")
MAX_VALUES = 12
MAX_VALUE_CHARS = 200
FORBIDDEN_WORDS = ("key", "secret", "token", "password", "value")


def _plain(item: Any) -> bool:
    """True for a text, number or boolean (not a nested thing)."""
    return isinstance(item, (str, int, float, bool))


def _check_one(name: Any, item: Any) -> str | None:
    """Return a plain reason this one fact is refused, or None."""
    if not isinstance(name, str) or not name:
        return "Every fact needs a name."
    if any(word in name.lower() for word in FORBIDDEN_WORDS):
        return f"The fact name '{name}' is not allowed: secrets must never be parked in a flow."
    if isinstance(item, list):
        parts = item
        if not all(isinstance(p, str) for p in parts):
            return f"The fact '{name}' may only be a list of text."
    elif _plain(item):
        parts = [item]
    else:
        return f"The fact '{name}' must be text, a number, a yes/no or a list of text, not a nested object."
    if any(len(str(p)) > MAX_VALUE_CHARS for p in parts) or len(str(item)) > MAX_VALUE_CHARS:
        return f"The fact '{name}' is longer than {MAX_VALUE_CHARS} characters."
    return None


def check_values(values: Any) -> str | None:
    """Return a plain reason the facts are refused, or None when they are fine."""
    if values is None:
        return None
    if not isinstance(values, dict):
        return "The facts must be a small object of names and plain values."
    if len(values) > MAX_VALUES:
        return f"At most {MAX_VALUES} facts can be kept."
    for name, item in values.items():
        reason = _check_one(name, item)
        if reason:
            return reason
    return None


def flow_card(flow: str, status: str, step: int, steps: int, label: str, values: dict | None) -> dict:
    """Return the card data for a flow's current step, or {"error": ...} saying what is wrong."""
    if status not in STATUSES:
        return {"error": f"The status must be one of: {', '.join(STATUSES)}."}
    if not flow.strip():
        return {"error": "The flow needs an id."}
    if steps < 1 or step < 0 or step > steps:
        return {"error": "The step must be between 0 and the number of steps."}
    reason = check_values(values)
    if reason:
        return {"error": reason}
    return {"flow": flow, "status": status, "step": step, "steps": steps, "label": label, "values": dict(values or {})}
