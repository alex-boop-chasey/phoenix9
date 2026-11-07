"""Card: the changes of one task attempt, split into files with added and removed counts."""
from phoenix9.ops import common, logs as ops_logs

schema = {"project": "str", "id": "str"}
MAX_LINES = 2000


def _split(lines: list[str]) -> list[dict]:
    """Group diff lines into files: {name, added, removed, lines}."""
    files: list[dict] = []
    for line in lines:
        if line.startswith("diff --git ") or not files:
            name = line.split(" b/", 1)[-1] if line.startswith("diff --git ") else "changes"
            files.append({"name": name, "added": 0, "removed": 0, "lines": []})
        current = files[-1]
        current["lines"].append(line)
        if line.startswith("+") and not line.startswith("+++"):
            current["added"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            current["removed"] += 1
    return files


def build(query: dict) -> dict:
    """The card: data is {id, files, truncated}; the action opens the Logs page on this diff."""
    project, log_id = query.get("project"), query.get("id")
    if not project or not log_id:
        raise common.OpsError("A diff card needs 'project' and 'id'.")
    read = ops_logs.read(project, log_id)
    if read["kind"] != "diff":
        raise common.OpsError("That log is not a diff. Pick one of kind 'diff' from the logs list.")
    lines = read["text"].splitlines()
    data = {"id": log_id, "files": _split(lines[:MAX_LINES]),
            "truncated": read["truncated"] or len(lines) > MAX_LINES}
    actions = [{"label": "Open in Logs", "kind": "route",
                "route": {"to": f"p/{project}/logs", "params": {"log": log_id}}}]
    return {"title": read["title"], "data": data, "actions": actions,
            "watch": {"projects": [project], "runs": [], "types": []}}
