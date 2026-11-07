"""Card: the projects list (same filters as the Projects page), with a link to each project."""
from phoenix9.ops import projects as ops_projects

schema = {"q": "str", "status": "str", "owner": "str", "sort": "str", "attention": "bool", "names": "list[str]"}


def build(query: dict) -> dict:
    """The card for these filters: data is the rows from ops.projects.query, actions open each project."""
    keys = ("q", "status", "owner", "sort", "attention")
    data = ops_projects.query(**{k: query[k] for k in keys if k in query})
    names = query.get("names")
    if names is not None:
        data = _only(data, names)
    rows = data["top"] + data["rest"]
    actions = [{"label": r["name"], "kind": "route",
                "route": {"to": f"p/{r['name']}/overview", "params": {}}} for r in rows]
    title = "Projects that need you" if query.get("attention") else "Projects"
    return {"title": title, "data": data, "actions": actions,
            "watch": {"projects": [], "runs": [], "types": ["project", "run", "gate"]}}


def _only(data: dict, names: list[str]) -> dict:
    """Keep only the named projects, in the order given."""
    by_name = {r["name"]: r for r in data["top"] + data["rest"]}
    top_names = {r["name"] for r in data["top"]}
    kept = [by_name[n] for n in dict.fromkeys(names) if n in by_name]
    top = [r for r in kept if r["name"] in top_names]
    return {**data, "top": top, "rest": [r for r in kept if r not in top], "total": len(kept)}
