"""Delete a project entirely: the dry-run plan, and the safety copy written before anything goes."""
import json
import os
import re
import signal
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phoenix9 import atomic, deploy, events, git, keys, paths, project, projectchat, runs, settings, state, status
from phoenix9.ops import common
from phoenix9.project_removal import PROTECTED, _save_removed, removed_list, untrust

ALLOWED_CALLERS = ("dashboard", "cli")
STILL_LIVE = "still live, take it down yourself"
NEWEST_RUNS = 5
STAMP_FORMAT = "%Y%m%d-%H%M"
STAMP_RE = re.compile(r"-(\d{8}-\d{4})$")
PURE_CACHES = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
               ".turbo"}             # rebuilt by a tool, never anyone's work: the only folders left out of the copy
PURE_CACHE_PAIRS = {(".next", "cache")}
URL_RE = re.compile(r"^https?://\S+$")
SYSTEMD_DIR = Path("/etc/systemd/system")
UNIT_GONE = ("not loaded", "does not exist", "not found", "no such file")
SCOPE_WORDS = ("delete_repo", "403")
LOCK_WAIT = 5.0            # seconds a delete waits for the project lock (a run start holds it briefly)
CLOSE_WAIT = 10.0          # seconds the delete waits for closed terminals and sessions before SIGKILL
CLOSE_POLL = 0.5
CHAIN_DEPTH = 64           # parents followed at most when sorting a process
PTY_HOST = "--type=ptyHost"     # code-server's terminal host: every VS Code terminal shell is its child
GRUNT_RE = re.compile(r"(^|[\s/])\.?grunt(\s|/|$)")    # grunt's engine, its tmux server or its files
INSTALLED = "/opt/phoenix9/"


OWN_SOURCES = ("empty", "template")   # project.json sources where Phoenix itself made the GitHub repo


def _repo(folder) -> str | None:
    """The project's GitHub repo as owner/name, or None (shown in the plan; NOT proof the project owns it)."""
    parts = project.split_repo(project.repo_of(folder))
    return f"{parts['owner']}/{parts['name']}" if parts["owner"] else None


def _key(repo) -> str | None:
    """owner/name in lower case for comparing repos (GitHub names ignore case), or None."""
    parts = project.split_repo(str(repo or ""))
    return f"{parts['owner']}/{parts['name']}".lower() if parts["owner"] else None


def _git_out(host, where, *args) -> str | None:
    """The trimmed output of one git command in `where` (through the host adapter), or None when it fails."""
    rc, out, _ = host.run(git.git_argv("-C", str(where), *args))
    return out.strip() if rc == 0 else None


def _users_of(key: str, name: str, host) -> list:
    """Who else points at this repo: every other folder in the projects folder (listed or not; its recorded repo,
    the origin of its code/ and of the folder itself), removed-projects rows, the projects folder's own repo."""
    users = []
    try:
        others = sorted(p for p in paths.projects().iterdir() if p.is_dir() and p.name != name)
    except OSError:
        others = []
    for other in others:
        try:
            theirs = [project._meta(other).get("repo")]
            theirs += [_git_out(host, where, "remote", "get-url", "origin")
                       for where in (other / "code", other) if (where / ".git").exists()]
        except Exception:       # an unreadable folder might use it: count it, to be safe
            theirs = [key]
        if key in {_key(t) for t in theirs}:
            users.append(f"{'project' if (other / 'CLAUDE.md').is_file() else 'folder'} {other.name}")
    users += [f"removed project {r['name']}" for r in removed_list()
              if r["name"] != name and _key(r.get("repo")) == key]
    if _key(_git_out(host, paths.projects(), "remote", "get-url", "origin")) == key:
        users.append(f"the projects folder {paths.projects()}")
    return users


def made_by_phoenix(folder: Path) -> bool:
    """Cheap guess (project.json only, no git or gh) whether Phoenix created the project's recorded repo;
    repo_verdict stays the final word."""
    meta = project._meta(folder)
    key = _key(meta.get("repo"))
    return bool(key and meta.get("source") in OWN_SOURCES and _key(meta.get("phoenix_made_repo")) == key)


def repo_verdict(name: str, folder: Path, host) -> dict:
    """Whether Phoenix may delete the project's GitHub repo: {repo, delete, why}.

    Only when every rule holds: Phoenix created the repo (project.json source empty/template with the repo
    recorded, and `phoenix_made_repo`, written only when Phoenix creates a repo, naming exactly that repo), code/ is its own git repo (not a plain folder inside a parent repo), code/'s origin is that repo,
    and no other project, removed-projects row or the projects folder's own repo points at it."""
    shown = _repo(folder)
    if not shown:
        return {"repo": None, "delete": False, "why": "There is no GitHub repo."}

    def keep(why: str) -> dict:
        return {"repo": shown, "delete": False, "reason": f"it {why}",
                "why": f"GitHub repo {shown} not deleted: it {why}."}
    key0 = _key(shown)
    if _key(_git_out(host, paths.projects(), "remote", "get-url", "origin")) == key0:
        return keep("is the projects folder's shared repo")
    code0 = folder / "code"
    if code0.is_dir() and not code0.is_symlink():
        top0 = _git_out(host, code0, "rev-parse", "--show-toplevel")
        if top0 and Path(os.path.realpath(folder)).is_relative_to(os.path.realpath(top0)):
            return keep("is the projects folder's shared repo" if os.path.realpath(top0) != os.path.realpath(folder)
                        else "is not this project's own repo")
    meta = project._meta(folder)
    key = _key(meta.get("repo"))
    if (meta.get("source") not in OWN_SOURCES or not key or key != _key(shown)
            or _key(meta.get("phoenix_made_repo")) != key):
        return keep("was not created by Phoenix")
    if not meta.get("phoenix_made_repo_id"):
        return keep("has no GitHub id recorded from when Phoenix created it, so Phoenix cannot be sure it is the same repo")
    code = folder / "code"
    if code.is_symlink() or not code.is_dir():
        return keep("is not this project's own repo")
    top = _git_out(host, code, "rev-parse", "--show-toplevel")
    if not top or os.path.realpath(top) != os.path.realpath(code):
        return keep("is not this project's own repo")
    if _key(_git_out(host, code, "remote", "get-url", "origin")) != key:
        return keep("is not this project's own repo")
    if not _git_out(host, code, "rev-list", "-n", "1", "--all"):
        return keep("has no commits here, so no bundle of it can be kept")
    users = _users_of(key, name, host)
    if users:
        return keep(f"is shared (also used by {', '.join(users)})")
    return {"repo": shown, "delete": True, "repo_id": str(meta["phoenix_made_repo_id"]),
            "why": f"GitHub repo {shown} will be deleted."}


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


def _unsaved(host, folder) -> int:
    """How many changes git has not committed (git status --porcelain lines); 0 when there is no repo."""
    code = folder / "code"
    if not (code / ".git").exists():
        return 0
    rc, out, _ = host.run(git.git_argv("-C", str(code), "status", "--porcelain"))
    return len([ln for ln in out.splitlines() if ln.strip()]) if rc == 0 else 0


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
    """The chat unit's name and state (unknown when it cannot be read)."""
    unit = f"claude-rc-chat@{name}"
    try:
        return {"unit": unit, "state": projectchat.state(name, adapters)["state"]}
    except Exception:       # a broken chat doc must not hide the rest of the plan
        return {"unit": unit, "state": "unknown"}


def _folder_refusals(name: str, folder: Path | None) -> list:
    """Refusals about the folder itself: a link, a folder that is really somewhere else, a protected project."""
    if folder is None:
        return []
    out = []
    real = Path(os.path.realpath(folder))
    if folder.is_symlink():
        out.append(f"{folder} is a link to {real}, so it cannot be deleted from here.")
    elif real.parent != Path(os.path.realpath(paths.projects())):
        out.append(f"{folder} is really {real}, outside the projects folder, so it cannot be deleted from here.")
    if real.name in PROTECTED and real.name != name:
        out.append(PROTECTED[real.name].replace("removed", "deleted"))
    return out


def _refusals(name: str, who: str, chat_state: str, folder: Path | None = None, adapters=None) -> list:
    """Plain sentences for everything that stops a delete (empty when it can run)."""
    out = []
    if name in PROTECTED:
        out.append(PROTECTED[name].replace("removed", "deleted"))
    out += _folder_refusals(name, folder)
    if who not in ALLOWED_CALLERS:
        out.append("Only Alex can delete a project, from the dashboard or the command line.")
    busy = [r for r in runs.list_runs(name) if r["status"] in status.ACTIVE]
    if busy:
        out.append(f"A build is {busy[0]['status']} ({busy[0]['run_id']}). Stop it or let it finish first.")
    if chat_state == "working":
        out.append("The project's chat is working right now. Wait until it is done.")
    planning = [p for p in _project_work(name)[1] if p.get("status") in ("queued", "running")]
    if planning:
        out.append(f"A planning session is {planning[0]['status']} ({planning[0]['id']}). Wait until it is done, "
                   "or abandon it first.")
    blocking = _blocking(_sort_inside(_working_inside(folder, adapters, name), adapters))
    if blocking:
        shown = ", ".join(p["words"] for p in blocking[:3]) + (" and more" if len(blocking) > 3 else "")
        out.append(f"Programs are working inside the project folder: {shown}. Close them first "
                   "(a grunt job, a desktop session...).")
    return out


def _process_table(host) -> dict:
    """{pid: (parent pid, command line)} of every process ({} when it cannot be read)."""
    try:
        return host.process_table()
    except Exception:
        return {}


def _chain(table: dict, pid: int) -> list:
    """The process and its parents, nearest first, up to the first one Phoenix cannot see."""
    out = [pid]
    while len(out) < CHAIN_DEPTH:
        parent = table.get(out[-1], (0, ""))[0]
        if parent in (0, 1) or parent in out or parent not in table:
            break
        out.append(parent)
    return out


def _program(cmd: str) -> str:
    """The program's base name from a command line ('' when empty)."""
    first = cmd.split(" ", 1)[0] if cmd else ""
    return os.path.basename(first)


def _is_claude(cmd: str, name: str = "") -> bool:
    """True for a Claude Code process (its program, or the script node runs, is claude)."""
    words = [os.path.basename(w) for w in cmd.split()[:2]]
    return name == "claude" or words[:1] == ["claude"] or (
        len(words) == 2 and words[0] in ("node", "bun") and words[1] in ("claude", "cli.js") and "claude" in cmd)


def _is_phoenix(cmd: str) -> bool:
    """True for a Phoenix process (the phoenix command, python -m phoenix9, or the installed copy)."""
    words = cmd.split()[:3]
    return (bool(words) and os.path.basename(words[0]) == "phoenix") or "-m phoenix9" in cmd or any(
        w.startswith(INSTALLED) for w in words)


def _sort_one(p: dict, table: dict, names: dict, inside: set) -> dict:
    """One process in the folder, sorted: {pid, name, close, words, group}; words name it in plain English."""
    pid, name = p["pid"], p.get("name") or "a program"
    chain = _chain(table, pid)
    cmds = [table.get(q, (0, ""))[1] for q in chain]
    if any(GRUNT_RE.search(c) for c in cmds):
        return {"pid": pid, "name": name, "close": False, "words": f"a grunt job ({name}, process {pid})"}
    if any(_is_phoenix(c) for c in cmds):
        return {"pid": pid, "name": name, "close": False, "words": f"a Phoenix build ({name}, process {pid})"}
    for i, cmd in enumerate(cmds[1:], start=1):
        if PTY_HOST in cmd:                    # the process just below code-server's ptyHost is the terminal's shell
            shell = chain[i - 1]
            label = names.get(shell) or _program(cmds[i - 1]) or name
            return {"pid": pid, "name": name, "close": True, "group": shell,
                    "words": f"VS Code terminal ({label})"}
    claudes = [q for q, c in zip(chain, cmds) if q in inside and _is_claude(c, names.get(q, ""))]
    if claudes:                                # a Claude session working in the folder, and what it started
        return {"pid": pid, "name": name, "close": True, "group": claudes[-1], "words": "Claude session"}
    return {"pid": pid, "name": name, "close": False, "words": f"{name} (process {pid})"}


def _sort_inside(found: list, adapters) -> list:
    """The processes working in the folder, each marked whether the delete closes it or it blocks the delete."""
    if not found:
        return []
    table = _process_table(adapters.host)
    names = {p["pid"]: p.get("name") or "" for p in found}
    inside = set(names)
    return [_sort_one(p, table, names, inside) for p in found]


def _blocking(sorted_: list) -> list:
    """The processes that stop the delete."""
    return [p for p in sorted_ if not p["close"]]


def _closing_words(sorted_: list) -> list:
    """One plain line per thing the delete will close (a terminal or Claude session once, however many processes)."""
    seen, out = set(), []
    for p in sorted_:
        if p["close"] and p["group"] not in seen:
            seen.add(p["group"])
            out.append(p["words"])
    return out


def _will_close(name: str, chat_state: str, folder: Path, adapters) -> list:
    """What the delete will close before removing anything: terminals and sessions in the folder, the chat."""
    words = _closing_words(_sort_inside(_working_inside(folder, adapters, name), adapters))
    if chat_state in ("waking", "awake", "working"):
        words.append("project chat")
    return words


def _wait_gone(pids: set, folder: Path, adapters) -> set:
    """Wait up to CLOSE_WAIT seconds for these processes to leave the folder; returns the ones still there."""
    clock = adapters.clock
    end = clock.now() + CLOSE_WAIT
    while True:
        left = pids & {p["pid"] for p in _working_inside(folder, adapters)}
        if not left or clock.now() >= end:
            return left
        clock.sleep(CLOSE_POLL)


def close_leftovers(name: str, folder: Path, adapters) -> str:
    """Close the VS Code terminals and Claude sessions working in the folder: SIGTERM, wait, then SIGKILL.

    Only processes whose working folder is inside the project folder are signalled (never their parents,
    so never code-server itself); returns plain words for the record ('' when there was nothing to close)."""
    found = [p for p in _sort_inside(_working_inside(folder, adapters, name), adapters) if p["close"]]
    if not found:
        return ""
    host = adapters.host
    pids = {p["pid"] for p in found}
    for pid in sorted(pids):
        host.signal_pid(pid, signal.SIGTERM)
    left = _wait_gone(pids, folder, adapters)
    for pid in sorted(left):                   # still in the folder after the wait: only those, and only now
        host.signal_pid(pid, signal.SIGKILL)
    if left:
        left = _wait_gone(left, folder, adapters)
    if left:
        shown = ", ".join(f"{p['words']} ({p['name']}, process {p['pid']})" for p in found if p["pid"] in left)
        raise common.OpsError(f"Could not close {shown}.")
    return f"Closed {', '.join(_closing_words(found))} ({len(pids)} {'process' if len(pids) == 1 else 'processes'})."


def _own_chat_pids(name: str, host, procs: list) -> set:
    """The project's own chat unit's main process and the listed processes below it that are also in that
    unit's own cgroup (/proc/<pid>/cgroup is the unit's ControlGroup); the delete stops that unit itself."""
    unit = f"claude-rc-chat@{name}"
    try:
        rc, out, _ = host.systemctl("show", "-p", "MainPID", "--value", unit)
        main = int(out.strip()) if rc == 0 else 0
        rc, out, _ = host.systemctl("show", "-p", "ControlGroup", "--value", unit)
        group = out.strip() if rc == 0 else ""
    except Exception:
        return set()
    if not main or not group.endswith(f"/{unit}.service"):
        return set()
    tree = {main}
    for _ in range(len(procs)):         # grow the set until no process has a parent in it
        more = {p["pid"] for p in procs if p.get("pid") not in tree and host.parent_pid(p.get("pid")) in tree}
        if not more:
            break
        tree |= more
    own = set()
    for pid in tree:
        try:
            if host.cgroup(pid) == group:
                own.add(pid)
        except Exception:              # cannot read it: not excused
            continue
    return own


def _project_work(name: str) -> tuple[list, list]:
    """(quick edits, planning sessions) of the project, from their records (empty when unreadable)."""
    from phoenix9 import edits, plans
    try:
        found_edits = edits.list_edits(name)
    except Exception:
        found_edits = []
    try:
        found_plans = plans.list_plans(name)
    except Exception:
        found_plans = []
    return found_edits, found_plans


def _work_folders(name: str) -> list:
    """(arcname, path) of the project's quick-edit copies and planning-session folders (kept in the safety copy)."""
    found_edits, found_plans = _project_work(name)
    out = []
    for e in found_edits:
        out.append((Path("edits") / e["id"], paths.home() / "edits" / e["id"]))
    for p in found_plans:
        out.append((Path("plans") / p["id"], paths.home() / "plans" / p["id"]))
    return [(arc, base) for arc, base in out if base.is_dir() and not base.is_symlink()]


def _working_inside(folder: Path | None, adapters, name: str | None = None) -> list:
    """Processes whose working folder is inside the project's real folder (not this process, its parent shell or the project's own chat)."""
    if folder is None or adapters is None:
        return []
    real = os.path.realpath(folder)
    me = {os.getpid(), os.getppid()}
    try:
        procs = adapters.host.process_cwds()
    except Exception:          # cannot tell: say nothing rather than block every delete
        return []
    found = [p for p in procs if p.get("pid") not in me and
             (os.path.realpath(p.get("cwd") or "/") == real or os.path.realpath(p.get("cwd") or "/").startswith(real + os.sep))]
    if found and name:                  # only ask systemd when something is there to excuse
        own = _own_chat_pids(name, adapters.host, procs)
        found = [p for p in found if p.get("pid") not in own]
    return found


def plan(name: str, who: str, adapters) -> dict:
    """The dry run: everything that deleting this project would remove, and what stops it; changes nothing."""
    folder = common.project_dir(name)
    host = adapters.host
    repo = _repo(folder)
    prs, note = _open_prs(host, repo)
    chat = _chat(name, adapters)
    result = {"name": name, "folder": str(folder), "size": host.du_bytes(folder), "repo": repo,
              "repo_delete": repo_verdict(name, folder, host), "open_prs": prs, "unpushed": _unpushed(host, folder),
              "unsaved_edits": _unsaved(host, folder), "runs": _runs(name),
              "keys": [k["name"] for k in keys.list_keys(name)], "chat": chat,
              "deployments": _deployments(name, folder),
              "refusals": _refusals(name, who, chat["state"], folder, adapters),
              "will_close": _will_close(name, chat["state"], folder, adapters),
              "safety_copy": str(paths.deleted_projects()),
              "keep_days": settings.delete_settings()["keep_days"]}
    if result["keys"]:
        result["keys_note"] = ("The saved keys are deleted and NOT kept in the safety copy. Copy their values "
                               "somewhere safe first if you will need them.")
    if note:
        result["open_prs_note"] = note
    return result


def _stamp(now: float) -> str:
    """The date and time (UTC) as YYYYMMDD-HHMM."""
    return datetime.fromtimestamp(now, timezone.utc).strftime(STAMP_FORMAT)




def _pure_cache(rel_parts) -> bool:
    """True when this path (relative parts) is, or is inside, a pure cache folder (rebuilt by a tool)."""
    parts = tuple(rel_parts)
    return any(p in PURE_CACHES for p in parts) or any(parts[i:i + 2] in PURE_CACHE_PAIRS for i in range(len(parts) - 1))


def _walk_code(code: Path, with_git: bool = False):
    """Every file and symlink in code/ for the copy: the whole working copy (uncommitted and staged edits,
    untracked files, nested repos with their own .git, build output), skipping only code/.git (that is the
    bundle) and pure caches. With with_git (no bundle was written) code/.git goes in too. Links are stored as
    links, never followed."""
    for root, dirs, files in os.walk(code):
        rel = Path(root).relative_to(code).parts
        keep = []
        for d in dirs:
            if (not rel and d == ".git" and not with_git) or _pure_cache((*rel, d)):
                continue
            if (Path(root) / d).is_symlink():
                yield Path(root) / d
                continue
            keep.append(d)
        dirs[:] = keep
        for f in files:
            if not rel and f == ".git" and not with_git:
                continue
            yield Path(root) / f


def _walk(base: Path, rel_base: tuple = ()):
    """Every file and symlink under base (as paths), not following links and skipping only pure caches.

    Build output (dist, build, target...) is kept: without git it may be the only copy of someone's work."""
    for root, dirs, files in os.walk(base):
        rel = (*rel_base, *Path(root).relative_to(base).parts)
        dirs[:] = [d for d in dirs if not _pure_cache((*rel, d))]
        for f in files:
            yield Path(root) / f
        for d in list(dirs):
            if (Path(root) / d).is_symlink():
                dirs.remove(d)
                yield Path(root) / d


def _project_files(host, folder: Path, with_git: bool = False) -> list:
    """Paths (relative to the project folder) for files.tar.gz: everything but pure caches and (unless with_git)
    code/.git."""
    out = []
    for entry in sorted(folder.iterdir()):
        if entry.name == "code" and entry.is_dir() and not entry.is_symlink():
            out += [p.relative_to(folder) for p in _walk_code(entry, with_git)]
            continue
        elif entry.is_dir() and not entry.is_symlink():
            found = [] if _pure_cache((entry.name,)) else list(_walk(entry, (entry.name,)))
        else:
            found = [entry]
        out += [p.relative_to(folder) for p in found if p.exists() or p.is_symlink()]
    return out


def _write_tar(dest: Path, base: Path, rels: list) -> list:
    """Write a .tar.gz of these paths (relative to base); returns the names stored."""
    names = []
    with tarfile.open(dest, "w:gz") as tar:
        for rel in rels:
            tar.add(base / rel, arcname=str(rel), recursive=False)
            names.append(str(rel))
    return names


def _run_files(name: str) -> list:
    """(arcname, path) for each folder that goes in runs.tar.gz: Phoenix's run folders and any work folders."""
    return [(Path(kind) / name, base) for kind, base in (("runs", paths.runs(name)), ("work", paths.home() / "work" / name))
            if base.is_dir()] + _work_folders(name)


def _write_runs_tar(dest: Path, name: str) -> int:
    """Write runs.tar.gz (HOME/runs/<name> and HOME/work/<name>); returns how many files it holds."""
    count = 0
    with tarfile.open(dest, "w:gz") as tar:
        for arc, base in _run_files(name):
            for f in _walk(base):
                tar.add(f, arcname=str(arc / f.relative_to(base)), recursive=False)
                count += 1
    return count


def _fetch(host, code: Path) -> str:
    """git fetch --all before bundling, so branches only on GitHub are in the bundle too; returns a note
    ('' when it worked or there is no repo). A failed fetch does not stop the copy."""
    if not (code / ".git").exists():
        return ""
    rc, out, err = host.run(git.git_argv("-C", str(code), "fetch", "--all", "--quiet"), timeout=300)
    if rc != 0:
        return (f"git fetch --all failed ({(err or out).strip()[:150]}), so the bundle holds what was on this server "
                "only.")
    return ""


def _bundle(host, code: Path, dest: Path) -> str:
    """Write repo.bundle for code/ and verify it; returns a note ('' when it worked, why it was skipped otherwise)."""
    if not (code / ".git").exists():
        return "There is no git repo, so repo.bundle was skipped."
    if not _git_out(host, code, "rev-list", "-n", "1", "--all"):
        return "The git repo has no commits yet, so repo.bundle was skipped (its files are in files.tar.gz)."
    rc, out, err = host.run(git.git_argv("-C", str(code), "bundle", "create", str(dest), "--all"), timeout=600)
    if rc != 0:
        raise common.OpsError(f"git could not bundle the code: {(err or out).strip()[:200]}")
    rc, out, err = host.run(git.git_argv("-C", str(code), "bundle", "verify", str(dest)), timeout=600)
    if rc != 0 or not dest.is_file():
        raise common.OpsError(f"the code bundle did not check out: {(err or out).strip()[:200]}")
    return ""


def _restore_text(name: str, folder: str, repo: str | None, bundle: bool) -> str:
    """The plain steps for RESTORE.md."""
    steps = [f"# Restore {name}", "",
             f"This is a safety copy of the project {name}, made before it was deleted from {folder}.", ""]
    n = 1
    if bundle:
        steps += [f"{n}. Make the folder and clone the code from the bundle:",
                  f"   `mkdir -p {folder} && git clone repo.bundle {folder}/code`"]
    else:
        steps += [f"{n}. Make the folder: `mkdir -p {folder}`"]
    n += 1
    steps += [f"{n}. Unpack the notes and the code's working copy over it: `tar -xzf files.tar.gz -C {folder}` "
              "(this brings back unsaved edits that were never committed, untracked files and nested repos)"]
    n += 1
    steps += [f"{n}. Optional: put the build history back: `tar -xzf runs.tar.gz -C <Phoenix home>` "
              "(run folders go to runs/, work folders to work/, quick-edit copies to edits/, planning sessions to plans/)."]
    n += 1
    where = repo or "<owner>/<name>"
    steps += [f"{n}. Recreate the GitHub repo and push: `gh repo create {where} --private --source {folder}/code --push`"
              if bundle else f"{n}. Create the GitHub repo again if you want one: `gh repo create {where} --private`"]
    n += 1
    steps += [f"{n}. In Phoenix, use Import and pick {folder}.", ""]
    return "\n".join(steps)


def _make_copy(name: str, who: str, adapters, dest: Path, now: float) -> None:
    """Fill the safety-copy folder; raises on any problem (the caller cleans up)."""
    folder = common.project_dir(name)
    host = adapters.host
    plan_ = plan(name, who, adapters)
    notes = [_fetch(host, folder / "code")]
    notes.append(_bundle(host, folder / "code", dest / "repo.bundle"))
    notes = [n for n in notes if n]
    rels = _project_files(host, folder, with_git=not (dest / "repo.bundle").is_file())
    stored = _write_tar(dest / "files.tar.gz", folder, rels)
    run_count = _write_runs_tar(dest / "runs.tar.gz", name)
    repo = plan_["repo"]
    has_bundle = (dest / "repo.bundle").is_file()
    bundle_of = _key(_git_out(host, folder / "code", "remote", "get-url", "origin")) if has_bundle else None
    manifest = {"name": name, "folder": str(folder), "repo": repo,
                "repo_url": project.repo_of(folder) or (f"https://github.com/{repo}" if repo else ""),
                "who": who, "when": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": sorted(p.name for p in dest.iterdir()) + ["manifest.json", "RESTORE.md"],
                "files_stored": stored, "run_files": run_count, "notes": notes,
                "repo_delete": plan_["repo_delete"], "bundle_of": bundle_of, "plan": plan_}
    manifest["files"] = sorted(set(manifest["files"]))
    (dest / "RESTORE.md").write_text(_restore_text(name, str(folder), repo, has_bundle), encoding="utf-8")
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def backup(name: str, who: str, adapters) -> Path:
    """Write the safety copy of a project under paths.deleted_projects(); on any error remove it and raise OpsError."""
    now = adapters.clock.now()
    root = paths.deleted_projects()
    dest = root / f"{name}-{_stamp(now)}"
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest.mkdir(mode=0o700)
        os.chmod(dest, 0o700)
    except FileExistsError:
        raise common.OpsError(f"A safety copy named {dest.name} already exists. Wait a minute and try again.")
    except OSError as e:
        raise common.OpsError(f"Could not make the safety-copy folder {dest}: {e}")
    try:
        _make_copy(name, who, adapters, dest, now)
    except Exception as e:
        adapters.host.remove_tree(dest)
        if isinstance(e, common.OpsError):
            raise
        raise common.OpsError(f"The safety copy failed, so nothing was deleted: {e}") from e
    return dest


def _copy_time(entry: Path) -> float | None:
    """When a safety copy was made (from its folder name, UTC seconds), or None if it is not one of ours."""
    m = STAMP_RE.search(entry.name)
    if not m or not (entry / "manifest.json").is_file():
        return None
    try:
        return datetime.strptime(m.group(1), STAMP_FORMAT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def prune_backups(adapters, now: float) -> list:
    """Remove safety copies older than delete.keep_days; returns the names removed."""
    root = paths.deleted_projects()
    cutoff = now - timedelta(days=settings.delete_settings()["keep_days"]).total_seconds()
    removed = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return removed
    for entry in entries:
        made = _copy_time(entry) if entry.is_dir() and not entry.is_symlink() else None
        if made is not None and made < cutoff:
            adapters.host.remove_tree(entry)
            removed.append(entry.name)
    return removed


def _unit_ok(rc: int, out: str, err: str) -> bool:
    """True when a systemctl call worked or only said the unit is not there."""
    return rc == 0 or any(w in f"{out} {err}".lower() for w in UNIT_GONE)


def stop_chat(name: str, host) -> str:
    """Stop and disable the chat unit, remove its drop-ins, reload systemd; raises OpsError if systemctl refuses."""
    unit = f"claude-rc-chat@{name}"
    for args in (("stop", unit), ("disable", unit)):
        rc, out, err = host.systemctl(*args)
        if not _unit_ok(rc, out, err):
            raise common.OpsError(f"systemctl {args[0]} {unit} failed: {(err or out).strip()[:200]}")
    host.remove_tree(SYSTEMD_DIR / f"{unit}.service.d")
    rc, out, err = host.systemctl("daemon-reload")
    if rc != 0:
        raise common.OpsError(f"systemctl daemon-reload failed: {(err or out).strip()[:200]}")
    return f"Stopped and removed the chat unit {unit}."


def _forget(name: str) -> str:
    """Drop the removed_projects row and the INDEX.md line for the project."""
    rows = removed_list()
    if any(r["name"] == name for r in rows):
        _save_removed([r for r in rows if r["name"] != name])
    index = paths.projects() / "INDEX.md"
    if index.is_file():
        keep = [ln for ln in index.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"| {name} |")]
        index.write_text("".join(ln + "\n" for ln in keep), encoding="utf-8")
    return "Removed it from the removed list and INDEX.md."


def scope_words(repo: str) -> str:
    """The plain sentence for a GitHub login that may not delete repos."""
    return (f"The GitHub repo {repo} was NOT deleted: Phoenix's GitHub login isn't allowed to delete repos. "
            "Delete it on GitHub, or run `gh auth refresh -h github.com -s delete_repo` once in your own "
            "terminal and press Delete repo again.")


def _gh_delete(repo: str | None, host) -> tuple[bool, str, bool]:
    """Delete the GitHub repo; returns (ok, words, refused_for_scope)."""
    if not repo:
        return True, "There is no GitHub repo.", False
    rc, out, err = host.gh("repo", "delete", repo, "--yes")
    if rc == 0:
        return True, f"Deleted the GitHub repo {repo}.", False
    text = (err or out).strip()
    if any(w in text.lower() for w in SCOPE_WORDS):
        return False, scope_words(repo), True
    return False, f"GitHub would not delete {repo}: {text[:200]}", False


def _step(steps: list, who: str, name: str, step: str, fn) -> None:
    """Run one delete step, record it in the steps and the commands log; a failure is recorded, not raised."""
    try:
        ok, words = True, fn()
    except Exception as e:
        ok, words = False, f"{e}"
    steps.append({"step": step, "ok": ok, "words": words})
    common.record_command(who, f"project delete {name}: {step} ({'ok' if ok else 'failed'})", name)


def _refuse(name: str, who: str, adapters) -> None:
    """Raise Conflict with the plain reasons when this project may not be deleted."""
    reasons = _refusals(name, who, _chat(name, adapters)["state"], common.project_dir(name), adapters)
    if reasons:
        raise common.Conflict(" ".join(reasons))


def delete(name: str, confirm_name: str, who: str, adapters) -> dict:
    """Delete a project entirely after a safety copy; returns {name, backup, steps, not_done, still_live}."""
    folder = common.project_dir(name)
    _refuse(name, who, adapters)
    if confirm_name != name:
        raise common.OpsError(f"Type the project's name ({name}) to confirm. Nothing was deleted.")
    lock = state.Lock(paths.project_lock(name), wait=LOCK_WAIT)
    try:
        lock.__enter__()
    except TimeoutError:
        raise common.Conflict(f"Something else is changing {name} right now (a build starting, or another delete). "
                              "Try again in a minute. Nothing was deleted.") from None
    try:
        return _delete_locked(name, who, adapters, folder)
    finally:
        lock.__exit__(None, None, None)


def _close_or_refuse(name: str, who: str, adapters, folder: Path, dest: Path) -> str:
    """Close the terminals and Claude sessions left in the folder, then check it again; when that fails or
    something is working there again, remove the safety copy and raise Conflict (nothing was deleted)."""
    try:
        closed = close_leftovers(name, folder, adapters)
        again = _sort_inside(_working_inside(folder, adapters, name), adapters)
        if again:
            shown = ", ".join(p["words"] for p in again[:3]) + (" and more" if len(again) > 3 else "")
            raise common.OpsError(f"Programs are working inside the project folder again: {shown}.")
    except common.OpsError as e:
        adapters.host.remove_tree(dest)
        common.record_command(who, f"project delete {name}: programs in the folder (failed: {e})", name)
        raise common.Conflict(f"{e} Nothing was deleted.") from None
    if closed:
        common.record_command(who, f"project delete {name}: programs in the folder ({closed})", name)
    return closed


def _delete_locked(name: str, who: str, adapters, folder: Path) -> dict:
    """The delete itself, run while holding the project lock (so no run of it can be queued meanwhile)."""
    _refuse(name, who, adapters)
    live = _deployments(name, folder)
    dest = backup(name, who, adapters)
    try:
        _refuse(name, who, adapters)        # the copy can take minutes: check again right before deleting
    except common.OpsError as e:
        adapters.host.remove_tree(dest)
        raise common.Conflict(f"{e} Nothing was deleted.") from None
    common.record_command(who, f"project delete {name}: safety copy written to {dest}", name)
    steps, not_done = [], []
    closed = _close_or_refuse(name, who, adapters, folder, dest)
    if closed:
        steps.append({"step": "programs in the folder", "ok": True, "words": closed})
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    verdict = _with_bundle(manifest, dest)
    repo = verdict["repo"]
    host = adapters.host

    def records() -> str:
        host.remove_tree(paths.runs(name))
        host.remove_tree(paths.home() / "work" / name)
        found_edits, found_plans = _project_work(name)
        for e in found_edits:            # quick-edit copies (their edit/<id> branches go with code/)
            host.remove_tree(paths.home() / "edits" / e["id"])
            host.remove_tree(paths.home() / "work" / f"edit-{e['id']}")
            host.remove_file(paths.home() / "edits" / f"{e['id']}.json")
        for p in found_plans:            # planning sessions: record, folder, lock and repo copy
            host.remove_tree(paths.home() / "plans" / p["id"])
            host.remove_tree(paths.home() / "work" / f"plan-{p['id']}")
            host.remove_file(paths.home() / "plans" / f"{p['id']}.json")
            host.remove_file(paths.home() / "plans" / f"{p['id']}.lock")
        return "Removed Phoenix's records, runs, quick edits and planning sessions for the project."

    def remove_folder() -> str:
        inside = _working_inside(folder, adapters)      # the chat unit is stopped now: nothing may be excused
        if inside:
            shown = ", ".join(f"{p['name']} (process {p['pid']})" for p in inside[:3])
            raise common.OpsError(f"Not removed: programs are still working inside {folder}: {shown}.")
        host.remove_tree(folder)
        if folder.exists():
            raise common.OpsError(f"Could not remove {folder}.")
        return f"Removed the folder {folder}."

    def remove_keys() -> str:
        host.remove_file(paths.keys() / f"{name}.toml")
        return "Removed the project's saved keys."

    def trust() -> str:
        untrust(host, folder)
        return "Removed Claude Code's folder trust entry."

    _step(steps, who, name, "chat unit", lambda: stop_chat(name, host))
    if steps[-1]["ok"]:                 # the chat could still be working in the folder: never remove it then
        _step(steps, who, name, "records and runs", records)
        _step(steps, who, name, "project folder", remove_folder)
        _step(steps, who, name, "saved keys", remove_keys)
        _step(steps, who, name, "folder trust", trust)
        _step(steps, who, name, "removed list and INDEX.md", lambda: _forget(name))
    else:
        steps[-1]["words"] += (" So nothing else was deleted: the project folder, its records and keys are all "
                               "still there. Stop the chat unit, then delete again.")
    folder_gone = any(s["step"] == "project folder" and s["ok"] for s in steps) and not folder.exists()
    blocker = None if folder_gone else (f"GitHub repo {repo} not deleted: the project folder could not be removed, "
                                        "so its repo is kept. Remove the folder, then press Delete repo again.")
    _github_step(steps, not_done, who, name, verdict, host, dest, blocker)
    events.emit("project.deleted", project=name, who=who, backup=str(dest), repo=repo)
    for s in steps:
        if not s["ok"] and s["step"] != "GitHub repo":
            not_done.append({"what": s["step"], "how": s["words"]})
    return {"name": name, "backup": str(dest), "steps": steps, "not_done": not_done, "still_live": live}


def _with_bundle(manifest: dict, copy: Path) -> dict:
    """The manifest's repo verdict, turned to keep unless the safety copy holds a verified bundle of that repo."""
    verdict = dict(manifest.get("repo_delete") or {"repo": manifest.get("repo"), "delete": False,
                                                   "why": "This safety copy does not say the repo was Phoenix's own."})
    bundle = copy / "repo.bundle"
    if verdict.get("delete") and not (bundle.is_file() and bundle.stat().st_size > 0
                                      and manifest.get("bundle_of") == _key(verdict.get("repo"))):
        verdict.update(delete=False, why=f"GitHub repo {verdict.get('repo')} not deleted: the safety copy has no "
                                         "bundle of it, so its history would be lost.")
    return verdict


def _ref_lines(text: str, sep: str | None) -> set:
    """{(ref, sha)} from `sha<sep>ref` lines (peeled tag lines `^{}` and HEAD left out)."""
    found = set()
    for line in text.splitlines():
        parts = line.strip().split(sep, 1)
        if len(parts) == 2 and parts[1].strip().startswith("refs/") and not parts[1].strip().endswith("^{}"):
            found.add((parts[1].strip(), parts[0].strip()))
    return found


def _github_matches_bundle(repo: str, copy: Path, host) -> str | None:
    """Why GitHub's repo must be kept because it holds something the bundle lacks (None when the bundle has it all).

    Every branch and tag on GitHub (`git ls-remote`), with its commit, must be in the verified bundle
    (`git bundle list-heads`); a failing ls-remote or list-heads keeps the repo."""
    rc, out, err = host.run(git.git_argv("ls-remote", "--heads", "--tags", f"https://github.com/{repo}.git"),
                            timeout=120)
    if rc != 0:
        return (f"GitHub repo {repo} not deleted: Phoenix could not list its branches to check them against the "
                f"safety copy ({(err or out).strip()[:150]}).")
    remote = _ref_lines(out, "\t")
    rc, out, err = host.run(git.git_argv("bundle", "list-heads", str(copy / "repo.bundle")), timeout=120)
    if rc != 0:
        return f"GitHub repo {repo} not deleted: Phoenix could not read the safety copy's bundle to compare."
    have = _ref_lines(out, None)
    have |= {("refs/heads/" + ref[len("refs/remotes/origin/"):], sha) for ref, sha in have
             if ref.startswith("refs/remotes/origin/")}     # a branch fetched from GitHub but never checked out
    missing = sorted(ref for ref, sha in remote - have)
    if missing:
        shown = ", ".join(r.split("/", 2)[-1] for r in missing[:5]) + (" and more" if len(missing) > 5 else "")
        return (f"GitHub repo {repo} not deleted: it has branches or tags that are not in the safety copy "
                f"({shown}). Fetch them into a copy first if you want them, then delete it on GitHub.")
    return None


def _same_repo_on_github(verdict: dict, host) -> str | None:
    """Why the repo must be kept because GitHub's repo by that name is not the one Phoenix created (by GitHub id)."""
    repo = verdict["repo"]
    rc, out, _ = host.gh("repo", "view", repo, "--json", "id,nameWithOwner")
    try:
        data = json.loads(out) if rc == 0 else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("id"):
        return f"GitHub repo {repo} not deleted: Phoenix could not read its GitHub id to check it is the same repo."
    if str(data["id"]) != str(verdict.get("repo_id")) or _key(data.get("nameWithOwner")) != _key(repo):
        return (f"GitHub repo {repo} not deleted: its GitHub id is not the one recorded when Phoenix created it, "
                "so it is a different repo now.")
    return None


def _last_checks(verdict: dict, copy: Path, host) -> str | None:
    """Checks made right before `gh repo delete`; the reason to keep the repo, or None."""
    return _same_repo_on_github(verdict, host) or _github_matches_bundle(verdict["repo"], copy, host)


def _github_step(steps: list, not_done: list, who: str, name: str, verdict: dict, host, copy: Path,
                 blocker=None) -> None:
    """Run the GitHub repo delete as a step; a refusal for lack of scope goes into not_done.

    A repo the verdict keeps (not this project's own, shared, not made by Phoenix) is never touched: the step
    is recorded as kept, with the reason. So is one the last checks right before the delete keep."""
    repo = verdict.get("repo")
    if verdict.get("delete") and blocker:
        steps.append({"step": "GitHub repo", "ok": False, "words": blocker})
        not_done.append({"what": f"GitHub repo {repo}", "how": blocker})
        common.record_command(who, f"project delete {name}: GitHub repo (not tried)", name)
        return
    why = verdict.get("why") if not verdict.get("delete") else _last_checks(verdict, copy, host)
    if not verdict.get("delete") or why:
        steps.append({"step": "GitHub repo", "ok": True, "kept": True, "words": why or "Kept."})
        common.record_command(who, f"project delete {name}: GitHub repo (kept)", name)
        return
    outcome = {}

    def run() -> str:
        ok, words, scope = _gh_delete(repo, host)
        outcome.update(ok=ok, scope=scope)
        if not ok:
            raise common.OpsError(words)
        return words
    _step(steps, who, name, "GitHub repo", run)
    if not steps[-1]["ok"]:
        how = ("Delete it on GitHub, or run `gh auth refresh -h github.com -s delete_repo` once in your own "
               "terminal and press Delete repo again." if outcome.get("scope") else steps[-1]["words"])
        not_done.append({"what": steps[-1]["words"] if outcome.get("scope") else f"GitHub repo {repo}", "how": how})


def _newest_copy(name: str) -> Path | None:
    """The newest safety-copy folder for this project name, or None."""
    found = []
    try:
        entries = list(paths.deleted_projects().iterdir())
    except OSError:
        return None
    for entry in entries:
        m = STAMP_RE.search(entry.name)
        if m and entry.name[:m.start()] == name and (entry / "manifest.json").is_file():
            found.append((m.group(1), entry))
    return max(found)[1] if found else None


def delete_repo(name: str, who: str, adapters) -> dict:
    """Retry only the GitHub repo delete, reading the repo from the newest safety copy's manifest.

    The same rules as the delete apply (the manifest's verdict, a bundle of that repo in the copy); it is also
    refused when the project folder exists again or any current project, removed row or the projects folder
    now uses the repo."""
    if name in PROTECTED or who not in ALLOWED_CALLERS:
        raise common.Conflict(" ".join(_refusals(name, who, "off")))
    copy = _newest_copy(name)
    if copy is None:
        raise common.NotFound(f"There is no safety copy for '{name}', so Phoenix does not know its GitHub repo.")
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    verdict = _with_bundle(manifest, copy)
    folder = paths.projects() / name
    if folder.exists() or folder.is_symlink():
        raise common.Conflict(f"The project folder {folder} exists again, so its GitHub repo is not deleted. "
                              "Delete the project again from its Settings tab if that is what you want.")
    key = _key(verdict.get("repo"))
    users = _users_of(key, name, adapters.host) if key else []
    if users:
        raise common.Conflict(f"GitHub repo {verdict.get('repo')} is not deleted: it is in use by {', '.join(users)}.")
    steps, not_done = [], []
    _github_step(steps, not_done, who, name, verdict, adapters.host, copy)
    events.emit("project.changed", project=name, who=who, what="github repo deleted" if steps[0]["ok"] and not steps[0].get("kept") else "github repo kept")
    return {"name": name, "backup": str(copy), "steps": steps, "not_done": not_done}
