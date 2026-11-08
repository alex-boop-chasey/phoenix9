"""Ops that move the dashboard: publish a ui.go event the open dashboard follows."""
from phoenix9 import events, routes
from phoenix9.ops import common


def go(to: str, params: dict | None, who: str) -> dict:
    """Check the route, publish a ui.go event ({hash, label, by}) and return {hash, label}."""
    found = routes.resolve(to, params or {})
    events.emit("ui.go", project=None, hash=found["hash"], label=found["label"], by="agent")
    common.record_command(who, "ui go " + to)
    return found
