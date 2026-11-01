"""GitHub recipe: check the project's repo is visible to the connected account (through the key proxy)."""
from phoenix9 import project

TOKEN_HEADER = "X-Phoenix-Proxy-Token"


def wire(ctx, service, proxy) -> dict:
    """Return {"ok": True} when the project's GitHub repo is reachable, else {"ok": False, "reason": ...}."""
    if proxy is None:
        return {"ok": True, "note": "GitHub not connected in Global settings; repo not checked"}
    repo = project.repo_of(ctx.project.dir)
    parts = project.split_repo(repo)
    if not parts["owner"]:
        return {"ok": True}
    slug = f"{parts['owner']}/{parts['name']}"
    status, _headers, _body = ctx.adapters.http.request(
        "GET", f"{proxy['url']}/repos/{slug}", headers={TOKEN_HEADER: proxy["token"]})
    if status == 200:
        return {"ok": True}
    if status == 404:
        return {"ok": False, "reason": f"GitHub repo {slug} not found or not visible to the connected account"}
    return {"ok": False, "reason": f"GitHub repo {slug} check answered {status}"}
