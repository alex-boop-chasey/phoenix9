"""Card: the open gates (questions waiting for Alex), optionally for one project."""
from phoenix9.ops import gates as ops_gates

schema = {"project": "str"}


def build(query: dict) -> dict:
    """The card: data is the open gates; no buttons here (the Needs-you card has its own)."""
    project = query.get("project") or None
    found = ops_gates.list_(project)
    return {"title": "Needs you" + (f" in {project}" if project else ""), "data": found, "actions": [],
            "watch": {"projects": [project] if project else [], "runs": [], "types": ["gate"]}}
