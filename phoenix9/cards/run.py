"""Card: one build run, with a link to the Build tab and a Stop button while it is active."""
from phoenix9 import status
from phoenix9.ops import common, runs as ops_runs

schema = {"project": "str", "run_id": "str"}


def _resolve(project: str, run_id: str) -> str:
    """The run id, with 'latest' turned into the project's newest run."""
    if run_id != "latest":
        return run_id
    found = ops_runs.list_(project)
    if not found:
        raise common.NotFound(f"{project} has no builds yet.")
    return found[0]["run_id"]


def build(query: dict) -> dict:
    """The card: data is ops.runs.detail; actions are Open build and, when active, Stop."""
    project = query.get("project")
    if not project or not query.get("run_id"):
        raise common.OpsError("A run card needs 'project' and 'run_id'.")
    run_id = _resolve(project, query["run_id"])
    data = ops_runs.detail(project, run_id)
    actions = [{"label": "Open build", "kind": "route",
                "route": {"to": f"p/{project}/build", "params": {"run": run_id}}}]
    if data["status"] in status.ACTIVE:
        actions.append({"label": "Stop build", "kind": "op",
                        "op": {"method": "POST", "path": f"/api/runs/{project}/{run_id}/stop",
                               "body": {"confirm": True}},
                        "confirm": "The build stops, and its unfinished work and branch are thrown away.",
                        "danger": True})
    return {"title": data.get("title") or f"Build {run_id}", "data": data, "actions": actions,
            "watch": {"projects": [project], "runs": [run_id], "types": ["run", "step", "task"]}}
