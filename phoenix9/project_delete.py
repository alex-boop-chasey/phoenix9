"""Delete a project entirely: the dry-run plan that shows exactly what would go (nothing is touched)."""
import json
import re

from phoenix9 import deploy, git, keys, paths, project, projectchat, runs, settings, status
from phoenix9.ops import common
from phoenix9.project_removal import PROTECTED

ALLOWED_CALLERS = ("dashboard", "cli")
STILL_LIVE = "still live, take it down yourself"
NEWEST_RUNS = 5
URL_RE = re.compile(r"^https?://\S+$")


def _repo(folder) -> str | None:
    """The project's GitHub repo as owner/name, or None."""
    parts = project.split_repo(project.repo_of(folder))
    return f"{parts['owner']}/{parts['name']}" if parts["owner"] else None


def _open_prs(host, repo: str | None) -> tuple[list, str]:
    """Open merge requests as ([{number, title, url}], note); the note says why the list may be empty."""
    if not repo:
        return [], "There is no GitHub repo."
    rc, out, err = host.gh("pr", "list", "--repo", repo, "--state", "open", "--json", "number,title,url")
    if rc != 0:
        return [], f"Could not ask GitHub for open merge requests: {(err or out).strip()[:200]}"
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return [], "GitHub gave an answer Phoenix could not read."
    return [{"number": r.get("number"), "title": r.get("title"), "url": r.get("url")}
            for r in rows if isinstance(r, dict)], ""


def _unpushed(host, folder) -> int:
    """Commits on any local branch that no remote branch has (all of them when there is no remote)."""
    code = folder / "code"
    if not (code / ".git").exists():
        return 0
    rc, out, _ = host.run(git.git_argv("-C", str(code), "rev-list", "--count", "--branches", "--not", "--remotes"))
    try:
        return int(out.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def _runs(name: str) -> dict:
    """{count, newest}: how many runs the project has and the ids of the newest few."""
    found = runs.list_runs(name)
    return {"count": len(found), "newest": [r["run_id"] for r in found[:NEWEST_RUNS]]}


def _links(values) -> list:
    """Every web address found in these values (nested settings included), in order, without repeats."""
    out = []
    for v in values:
        if isinstance(v, dict):
            out += _links(v.values())
        elif isinstance(v, str) and URL_RE.match(v) and v not in out:
            out.append(v)
    return out


def _deployments(name: str, folder) -> list:
    """Live deploy targets from phoenix.toml [deploy] and the deploy records, each marked still live."""
    try:
        table = settings.load_project(folder).get("deploy", {})
    except settings.SettingsError:
        table = {}
    records = [r for r in deploy.read_records(name) if r.get("ok") and r.get("kind") == "deploy"]
    target = table.get("with") or (records[-1].get("deployer") if records else None)
    links = _links(list(table.get("settings", {}).values()) + [r.get("url") for r in records])
    if not target or (target == deploy.NONE and not links):
        return []
    return [{"target": target, "links": links, "note": STILL_LIVE}]


def _chat(name: str, adapters) -> dict:
    """The chat unit's name and state (off when it cannot be read)."""
    unit = f"claude-rc-chat@{name}"
    try:
        return {"unit": unit, "state": projectchat.state(name, adapters)["state"]}
    except Exception:       # a broken chat doc must not hide the rest of the plan
        return {"unit": unit, "state": "off"}


def _refusals(name: str, who: str, chat_state: str) -> list:
    """Plain sentences for everything that stops a delete (empty when it can run)."""
    out = []
    if name in PROTECTED:
        out.append(PROTECTED[name].replace("removed", "deleted"))
    if who not in ALLOWED_CALLERS:
        out.append("Only Alex can delete a project, from the dashboard or the command line.")
    busy = [r for r in runs.list_runs(name) if r["status"] in status.ACTIVE]
    if busy:
        out.append(f"A build is {busy[0]['status']} ({busy[0]['run_id']}). Stop it or let it finish first.")
    if chat_state == "working":
        out.append("The project's chat is working right now. Wait until it is done.")
    return out


def plan(name: str, who: str, adapters) -> dict:
    """The dry run: everything that deleting this project would remove, and what stops it; changes nothing."""
    folder = common.project_dir(name)
    host = adapters.host
    repo = _repo(folder)
    prs, note = _open_prs(host, repo)
    chat = _chat(name, adapters)
    result = {"name": name, "folder": str(folder), "size": host.du_bytes(folder), "repo": repo,
              "open_prs": prs, "unpushed": _unpushed(host, folder), "runs": _runs(name),
              "keys": [k["name"] for k in keys.list_keys(name)], "chat": chat,
              "deployments": _deployments(name, folder),
              "refusals": _refusals(name, who, chat["state"]),
              "safety_copy": str(paths.deleted_projects())}
    if note:
        result["open_prs_note"] = note
    return result
