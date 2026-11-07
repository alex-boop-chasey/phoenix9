"""Card: pull requests of one project (or every project with a GitHub repo), with a link to each."""
from phoenix9.ops import github as ops_github

schema = {"project": "str", "state": "str"}


def build(query: dict) -> dict:
    """The card: data is the pull request rows, actions open each pull request on GitHub."""
    project = query.get("project") or None
    state = query.get("state") or "open"
    rows = ops_github.prs(project, state)
    actions = [{"label": f"#{r['number']} {r['title']}", "kind": "link", "href": r["url"]}
               for r in rows if r.get("url")]
    where = f" in {project}" if project else ""
    return {"title": f"{state.capitalize()} pull requests{where}", "data": rows, "actions": actions,
            "watch": {"projects": [project] if project else [], "runs": [], "types": [], "poll_s": 60}}
