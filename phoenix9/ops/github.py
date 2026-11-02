"""Ops for GitHub: whether the host's gh login works, and which repos it can see."""
from phoenix9.ops import common


def _accounts(host) -> list:
    """The signed-in user plus the organisations they belong to."""
    rc, out, _ = host.gh("api", "user", "--jq", ".login")
    names = [out.strip()] if rc == 0 and out.strip() else []
    rc, out, _ = host.gh("api", "user/orgs", "--jq", ".[].login")
    if rc == 0:
        names += [x.strip() for x in out.splitlines() if x.strip()]
    return names


def status() -> dict:
    """{connected, accounts}: connected means `gh auth status` works on the host."""
    host = common.make_adapters().host
    if host.gh("auth", "status")[0] != 0:
        return {"connected": False, "accounts": []}
    return {"connected": True, "accounts": _accounts(host)}


def repos() -> dict:
    """{connected, repos: [{full_name, owner, private}]} for each account the login can see."""
    import json
    host = common.make_adapters().host
    info = status()
    found = []
    for account in info["accounts"]:
        rc, out, _ = host.gh("repo", "list", account, "--json", "nameWithOwner,isPrivate", "--limit", "200")
        if rc != 0:
            continue
        try:
            items = json.loads(out or "[]")
        except ValueError:
            continue
        for item in items:
            full = item.get("nameWithOwner", "")
            if "/" in full:
                found.append({"full_name": full, "owner": full.split("/")[0], "private": bool(item.get("isPrivate"))})
    return {"connected": info["connected"], "repos": found}
