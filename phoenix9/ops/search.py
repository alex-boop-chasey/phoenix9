"""Ops for search: find projects, runs, notes, research and run logs by plain text (read-only)."""
from phoenix9 import routes, search as core
from phoenix9.ops.common import OpsError


def _opened(item: dict):
    """The result with its page checked by routes (hash and label added), or None when the page is gone."""
    try:
        return {**item, "page": {**item["page"], **routes.resolve(item["page"]["to"], item["page"]["params"])}}
    except OpsError:
        return None


def run(q: str, kind: str | None = None, limit: int = 20) -> dict:
    """Search projects, builds, notes, research and logs for some text; each result says which page opens it."""
    found = core.search(q, [kind] if kind else None, limit)
    return {"query": q.strip(), "kind": kind, "results": [r for r in map(_opened, found) if r]}
