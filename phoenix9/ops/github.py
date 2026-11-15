"""Ops for GitHub: whether the host's gh login works, and which repos it can see."""
from phoenix9 import proc
from phoenix9.ops import common

USER_WHAT = "Reading the GitHub account"
ORGS_WHAT = "Reading the GitHub account's organisations"
REPOS_WHAT = "Listing the repos on GitHub"
PRS_WHAT = "Listing the merge requests on GitHub"


def _accounts(host, problems: list | None = None) -> list:
    """The signed-in user plus the organisations they belong to; why a lookup failed is added to `problems`."""
    problems = [] if problems is None else problems
    result = host.gh("api", "user", "--jq", ".login", what=USER_WHAT)
    rc, out, _ = result
    names = [out.strip()] if rc == 0 and out.strip() else []
    if rc != 0:
        problems.append(proc.failure_text(USER_WHAT, result))
    result = host.gh("api", "user/orgs", "--jq", ".[].login", what=ORGS_WHAT)
    rc, out, _ = result
    if rc == 0:
        names += [x.strip() for x in out.splitlines() if x.strip()]
    else:
        problems.append(proc.failure_text(ORGS_WHAT, result))
    return names


def status() -> dict:
    """{connected, accounts}: connected means `gh auth status` works on the host."""
    host = common.make_adapters().host
    if host.gh("auth", "status")[0] != 0:
        return {"connected": False, "accounts": []}
    return {"connected": True, "accounts": _accounts(host)}


def repos() -> dict:
    """{connected, repos: [{full_name, owner, private}], problems} for each account the login can see; `problems`
    says in plain words why a GitHub lookup failed (empty when none did)."""
    import json
    host = common.make_adapters().host
    problems: list = []
    connected = host.gh("auth", "status")[0] == 0
    accounts = _accounts(host, problems) if connected else []
    found = []
    for account in accounts:
        result = host.gh("repo", "list", account, "--json", "nameWithOwner,isPrivate", "--limit", "200",
                         what=REPOS_WHAT)
        rc, out, _ = result
        if rc != 0:
            problems.append(proc.failure_text(REPOS_WHAT, result))
            continue
        try:
            items = json.loads(out or "[]")
        except ValueError:
            continue
        for item in items:
            full = item.get("nameWithOwner", "")
            if "/" in full:
                found.append({"full_name": full, "owner": full.split("/")[0], "private": bool(item.get("isPrivate"))})
    return {"connected": connected, "repos": found, "problems": problems}


PR_FIELDS = "number,title,state,isDraft,statusCheckRollup,url,updatedAt"
PR_CACHE_S = 60
_pr_cache: dict = {}          # (repo, state) -> (time, rows or error text)
_BAD = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}


def _checks(rollup) -> str:
    """One word for a pull request's checks: passing, failing, pending or none."""
    if not rollup:
        return "none"
    words = [str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup]
    if any(w in _BAD for w in words):
        return "failing"
    if any(w in _WAIT or w == "" for w in words):
        return "pending"
    return "passing"


def _fetch_prs(host, repo: str, state: str):
    """(rows, error) from gh for one repo, using the 60 second cache."""
    import json
    import time
    now = time.monotonic()
    hit = _pr_cache.get((repo, state))
    if hit and now - hit[0] < PR_CACHE_S:
        return hit[1], hit[2]
    result = host.gh("pr", "list", "--repo", repo, "--state", state, "--json", PR_FIELDS, what=PRS_WHAT)
    rc, out, _ = result
    rows, error = [], None
    if rc != 0:
        error = proc.failure_text(PRS_WHAT, result)
    else:
        try:
            rows = json.loads(out or "[]")
        except ValueError:
            error = "GitHub gave an answer that could not be read."
    _pr_cache[(repo, state)] = (now, rows, error)
    return rows, error


def _pr_row(project: str, item: dict) -> dict:
    """One pull request in Phoenix's row shape."""
    return {"project": project, "number": item.get("number"), "title": item.get("title", ""),
            "state": str(item.get("state", "")).lower(), "draft": bool(item.get("isDraft")),
            "checks": _checks(item.get("statusCheckRollup")), "url": item.get("url", ""),
            "updated_at": item.get("updatedAt", "")}


def _repo_projects(project: str | None) -> list:
    """[(project name, owner/name)] for one project or every project with a GitHub repo."""
    from phoenix9.ops import projects as ops_projects
    found = ops_projects.list_([project] if project else None)
    return [(r["name"], f"{r['repo_owner']}/{r['repo_name']}") for r in found if r.get("repo_owner")]


def prs(project: str | None = None, state: str = "open") -> list:
    """Pull request rows {project, number, title, state, draft, checks, url, updated_at}; a failed project gives {project, error}."""
    if state not in ("open", "closed", "merged", "all"):
        raise common.OpsError("state must be open, closed, merged or all.")
    host = common.make_adapters().host
    out = []
    for name, repo in _repo_projects(project):
        rows, error = _fetch_prs(host, repo, state)
        if error:
            out.append({"project": name, "error": error})
        out += [_pr_row(name, item) for item in rows]
    return out
