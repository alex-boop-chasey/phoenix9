"""Card: the last lines of one log of a project, scrubbed, with a link to the Logs page."""
from phoenix9.ops import common, logs as ops_logs

schema = {"project": "str", "id": "str", "tail": "int", "lines": "int"}
MAX_LINES = 200
DEFAULT_LINES = 50


def _count(query: dict) -> int:
    """How many lines to show: 'tail' or 'lines', between 1 and MAX_LINES (default 50)."""
    wanted = query.get("tail", query.get("lines", DEFAULT_LINES))
    return max(1, min(wanted, MAX_LINES))


def build(query: dict) -> dict:
    """The card: data is {id, kind, lines, truncated}; the action opens the log on the Logs page."""
    project, log_id = query.get("project"), query.get("id")
    if not project or not log_id:
        raise common.OpsError("A log card needs 'project' and 'id'.")
    read = ops_logs.read(project, log_id)
    lines = read["text"].splitlines()
    count = _count(query)
    data = {"id": log_id, "kind": read["kind"], "lines": lines[-count:],
            "truncated": read["truncated"] or len(lines) > count}
    actions = [{"label": "Open log", "kind": "route",
                "route": {"to": f"p/{project}/logs", "params": {"log": log_id}}}]
    return {"title": read["title"], "data": data, "actions": actions,
            "watch": {"projects": [project], "runs": [], "types": []}}
