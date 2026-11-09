"""Card: planning sessions (all, or one project's) with status, spec and Abandon."""
from phoenix9 import plans

schema = {"project": "str"}
ABANDONABLE = plans.ABANDONABLE


def _rows(project: str | None) -> list[dict]:
    """The sessions as rows: id, project, brief, status, spec, open_questions, last_activity."""
    keys = ("id", "project", "brief", "status", "spec", "open_questions", "last_activity")
    return [{k: p.get(k) for k in keys} for p in plans.list_plans(project)]


def build(query: dict) -> dict:
    """The card: data is the rows; Abandon (with confirm) is offered on a session that is not running or abandoned."""
    project = query.get("project") or None
    rows = _rows(project)
    actions = [{"label": f"Abandon {r['brief'][:40]}", "kind": "op",
                "op": {"method": "POST", "path": f"/api/plans/{r['id']}/abandon", "body": {"confirm": True}},
                "confirm": "The planning session is given up. The spec file stays where it is.", "danger": True}
               for r in rows if r["status"] in ABANDONABLE]
    return {"title": f"Planning sessions of {project}" if project else "Planning sessions", "data": rows,
            "actions": actions,
            "watch": {"projects": [project] if project else [], "runs": [], "types": ["plan"]}}
