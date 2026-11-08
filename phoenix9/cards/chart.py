"""Card: a small bar chart or sparkline of numbers proposed by the agent."""
from phoenix9.ops import common

schema = {"kind": "str", "series": "list"}
inline = True
KINDS = ("bars", "spark")
MAX_SERIES, MAX_BARS = 60, 20


def _point(item) -> dict:
    """One {label, value} point with a numeric value."""
    if not isinstance(item, dict) or set(item) != {"label", "value"}:
        raise common.OpsError("Every chart point must be {label, value}.")
    label, value = item["label"], item["value"]
    if not isinstance(label, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise common.OpsError("A chart point needs a text label and a numeric value.")
    if value != value or value in (float("inf"), float("-inf")):
        raise common.OpsError("A chart value must be a finite number.")
    return {"label": label[:200], "value": value}


def build(query: dict) -> dict:
    """The card: data is {kind, series, footer}; bad shapes are refused with a plain reason."""
    kind, series = query.get("kind", "bars"), query.get("series")
    if kind not in KINDS:
        raise common.OpsError("A chart card's kind must be 'bars' or 'spark'.")
    if not series:
        raise common.OpsError("A chart card needs a series with at least one point.")
    limit = MAX_BARS if kind == "bars" else MAX_SERIES
    if len(series) > limit:
        raise common.OpsError(f"A {kind} chart can have at most {limit} points.")
    return {"title": "Chart", "data": {"kind": kind, "series": [_point(s) for s in series],
                                       "footer": "proposed by the agent"},
            "actions": [], "watch": {"projects": [], "runs": [], "types": []}}
