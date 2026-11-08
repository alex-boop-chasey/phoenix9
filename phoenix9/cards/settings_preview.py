"""Card: a change to a project's settings proposed by the agent, checked without saving, with an Apply button."""
from phoenix9.ops import common, settings as ops_settings

schema = {"project": "str", "set": "dict"}
inline = True
MAX_KEYS = 20


def _lookup(values: dict, key: str):
    """The current value at a dotted key, or None when it is not there."""
    node = values
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _confirm(rows: list[dict]) -> str:
    """The confirm text listing every change."""
    return "Change " + "; ".join(f"{r['key']}: {r['before']} → {r['after']}" for r in rows) + "?"


def build(query: dict) -> dict:
    """The card: data is {rows: [{key, before, after, ok, reason}], footer}; Apply sets only the ok rows.

    Safety settings (sites, diff rules, safety files, services, tools, MCP, safety steps) are never ok here."""
    project, changes = query.get("project"), query.get("set")
    if not project or not isinstance(changes, dict) or not 1 <= len(changes) <= MAX_KEYS:
        raise common.OpsError(f"A settings-preview card needs 'project' and 'set' with 1 to {MAX_KEYS} keys.")
    if not all(isinstance(k, str) and k for k in changes):
        raise common.OpsError("Every key in 'set' must be a dotted setting name.")
    current = ops_settings.show(project)["values"]
    checked = {r["key"]: r for r in ops_settings.dry_check(project, changes, agent=True)}
    rows = [{"key": k, "before": _lookup(current, k), "after": v, "ok": checked[k]["ok"],
             "reason": checked[k]["reason"]} for k, v in changes.items()]
    good = [r for r in rows if r["ok"]]
    actions = []
    if good:
        label = "Apply" if len(good) == len(rows) else f"Apply {len(good)} of {len(rows)}"
        actions.append({"label": label, "kind": "op", "confirm": _confirm(good),
                        "op": {"method": "POST", "path": f"/api/projects/{project}/settings",
                               "body": {"set": {r["key"]: changes[r["key"]] for r in good}}}})
    return {"title": f"Settings change for {project}",
            "data": {"rows": rows, "footer": "proposed by the agent"}, "actions": actions,
            "watch": {"projects": [project], "runs": [], "types": ["settings."]}}
