"""Card: the Phoenix 9 version status, with a link to the update settings and Install when one is ready."""
from phoenix9.ops import update as ops_update

schema: dict = {}


def build(query: dict) -> dict:
    """The card: data is ops.update.status; Install uses the dashboard's route and body."""
    data = ops_update.status()
    actions = [{"label": "Open update settings", "kind": "route",
                "route": {"to": "settings", "params": {"section": "updates"}}}]
    if data.get("update_available") and data.get("newest"):
        actions.append({"label": f"Install {data['newest']}", "kind": "op",
                        "op": {"method": "POST", "path": "/api/update/install",
                               "body": {"yes": True, "tag": data["newest"]}},
                        "confirm": "Phoenix 9 installs the new version and restarts.", "danger": True})
    return {"title": "Phoenix 9 updates", "data": data, "actions": actions,
            "watch": {"projects": [], "runs": [], "types": ["update"]}}
