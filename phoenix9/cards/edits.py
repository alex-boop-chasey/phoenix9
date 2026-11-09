"""Card: quick edits (all, or one project's) with status, merge request link and Abandon."""
from phoenix9 import edits

schema = {"project": "str"}
OPEN = ("open", "stalled")


def _rows(project: str | None) -> list[dict]:
    """The quick edits as rows: id, project, title, status, last_activity, pr."""
    keys = ("id", "project", "title", "status", "last_activity")
    return [{**{k: e.get(k) for k in keys}, "pr": e.get("pr")} for e in edits.list_edits(project)]


def build(query: dict) -> dict:
    """The card: data is the rows; actions link each merge request and offer Abandon (with confirm) on open edits."""
    project = query.get("project") or None
    rows = _rows(project)
    actions = []
    for r in rows:
        if r["pr"]:
            actions.append({"label": f"Merge request for {r['title']}", "kind": "link", "href": r["pr"]})
        if r["status"] in OPEN:
            actions.append({"label": f"Abandon {r['title']}", "kind": "op",
                            "op": {"method": "POST", "path": f"/api/edits/{r['id']}/abandon", "body": {"confirm": True}},
                            "confirm": "The branch copy and its unfinished work are thrown away.", "danger": True})
    return {"title": f"Quick edits of {project}" if project else "Quick edits", "data": rows, "actions": actions,
            "watch": {"projects": [project] if project else [], "runs": [], "types": ["edit"]}}
