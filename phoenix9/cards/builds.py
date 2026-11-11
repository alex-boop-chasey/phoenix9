"""Card: a project's recent builds, newest first."""
from phoenix9.ops import common, runs as ops_runs

schema = {"project": "str", "limit": "int"}
MAX_LIMIT = 20


def build(query: dict) -> dict:
    """The card: data is the newest builds from ops.runs.builds (default 5, at most 20)."""
    project = query.get("project")
    if not project:
        raise common.OpsError("A builds card needs 'project'.")
    limit = query.get("limit", 5)
    if limit < 1 or limit > MAX_LIMIT:
        raise common.OpsError(f"'limit' must be from 1 to {MAX_LIMIT}.")
    return {"title": f"Builds of {project}", "data": ops_runs.builds(project, limit), "actions": [],
            "watch": {"projects": [project], "runs": [], "types": ["run"]}}
