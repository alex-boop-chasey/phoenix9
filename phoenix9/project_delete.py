"""Delete a project entirely: the dry-run plan, and the safety copy written before anything goes."""
import json
import os
import re
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phoenix9 import deploy, events, git, keys, paths, project, projectchat, runs, settings, status
from phoenix9.ops import common
from phoenix9.project_removal import PROTECTED, _save_removed, removed_list, untrust

ALLOWED_CALLERS = ("dashboard", "cli")
STILL_LIVE = "still live, take it down yourself"
NEWEST_RUNS = 5
STAMP_FORMAT = "%Y%m%d-%H%M"
STAMP_RE = re.compile(r"-(\d{8}-\d{4})$")
CACHE_DIRS = {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".nuxt", ".cache",
              ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".gradle", "target", ".parcel-cache",
              ".turbo", ".svelte-kit", ".eggs"}
URL_RE = re.compile(r"^https?://\S+$")
SYSTEMD_DIR = Path("/etc/systemd/system")
UNIT_GONE = ("not loaded", "does not exist", "not found", "no such file")
SCOPE_WORDS = ("delete_repo", "403")


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
    """Who else points at this repo: other listed projects, removed-projects rows, the projects folder's own repo."""
    users = []
    for other in project.project_names():
        if other == name:
            continue
        try:
            theirs = project.repo_of(paths.projects() / other)
        except Exception:       # an unreadable project might use it: count it, to be safe
            theirs = key
        if _key(theirs) == key:
            users.append(f"project {other}")
    users += [f"removed project {r['name']}" for r in removed_list()
              if r["name"] != name and _key(r.get("repo")) == key]
    if _key(_git_out(host, paths.projects(), "remote", "get-url", "origin")) == key:
        users.append(f"the projects folder {paths.projects()}")
    return users


def repo_verdict(name: str, folder: Path, host) -> dict:
    """Whether Phoenix may delete the project's GitHub repo: {repo, delete, why}.

    Only when every rule holds: Phoenix created the repo (project.json source empty/template with the repo
    recorded), code/ is its own git repo (not a plain folder inside a parent repo), code/'s origin is that repo,
    and no other project, removed-projects row or the projects folder's own repo points at it."""
    shown = _repo(folder)
    if not shown:
        return {"repo": None, "delete": False, "why": "There is no GitHub repo."}

    def keep(why: str) -> dict:
        return {"repo": shown, "delete": False, "why": f"GitHub repo {shown} not deleted: it {why}."}
    meta = project._meta(folder)
    key = _key(meta.get("repo"))
    if meta.get("source") not in OWN_SOURCES or not key or key != _key(shown):
        return keep("was not created by Phoenix")
    code = folder / "code"
    if code.is_symlink() or not code.is_dir():
        return keep("is not this project's own repo")
    top = _git_out(host, code, "rev-parse", "--show-toplevel")
    if not top or os.path.realpath(top) != os.path.realpath(code):
        return keep("is not this project's own repo")
    if _key(_git_out(host, code, "remote", "get-url", "origin")) != key:
        return keep("is not this project's own repo")
    users = _users_of(key, name, host)
    if users:
        return keep(f"is shared (also used by {', '.join(users)})")
    return {"repo": shown, "delete": True, "why": f"GitHub repo {shown} will be deleted."}


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
              "repo_delete": repo_verdict(name, folder, host), "open_prs": prs, "unpushed": _unpushed(host, folder), "runs": _runs(name),
              "keys": [k["name"] for k in keys.list_keys(name)], "chat": chat,
              "deployments": _deployments(name, folder),
              "refusals": _refusals(name, who, chat["state"]),
              "safety_copy": str(paths.deleted_projects())}
    if note:
        result["open_prs_note"] = note
    return result


def _stamp(now: float) -> str:
    """The date and time (UTC) as YYYYMMDD-HHMM."""
    return datetime.fromtimestamp(now, timezone.utc).strftime(STAMP_FORMAT)


def _skip(rel_parts) -> bool:
    """True when any folder on this path is a cache or build folder."""
    return any(part in CACHE_DIRS or part.endswith(".egg-info") for part in rel_parts[:-1]) or rel_parts[-1] in CACHE_DIRS


def _untracked(host, code: Path) -> list:
    """Paths (relative to code/) that git does not track, ignored ones too; raises OpsError if git fails."""
    rc, out, err = host.run(git.git_argv("-C", str(code), "ls-files", "-z", "--others"))
    if rc != 0:
        raise common.OpsError(f"git could not list the untracked files: {(err or out).strip()[:200]}")
    return [p for p in out.split("\0") if p]


def _walk(base: Path):
    """Every file and symlink under base (as paths), not following links and skipping cache folders."""
    for root, dirs, files in os.walk(base):
        rel = Path(root).relative_to(base).parts
        dirs[:] = [d for d in dirs if not _skip((*rel, d))]
        for f in files:
            yield Path(root) / f
        for d in list(dirs):
            if (Path(root) / d).is_symlink():
                dirs.remove(d)
                yield Path(root) / d


def _project_files(host, folder: Path) -> list:
    """Paths (relative to the project folder) for files.tar.gz: everything but code/'s tracked files and caches."""
    out = []
    for entry in sorted(folder.iterdir()):
        if entry.name == "code" and entry.is_dir() and not entry.is_symlink():
            if (entry / ".git").exists():
                found = [entry / p for p in _untracked(host, entry)]
            else:
                found = list(_walk(entry))
        elif entry.is_dir() and not entry.is_symlink():
            found = list(_walk(entry)) if entry.name not in CACHE_DIRS else []
        else:
            found = [entry]
        out += [p.relative_to(folder) for p in found if not _skip(p.relative_to(folder).parts) and (p.exists() or p.is_symlink())]
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
            if base.is_dir()]


def _write_runs_tar(dest: Path, name: str) -> int:
    """Write runs.tar.gz (HOME/runs/<name> and HOME/work/<name>); returns how many files it holds."""
    count = 0
    with tarfile.open(dest, "w:gz") as tar:
        for arc, base in _run_files(name):
            for f in _walk(base):
                tar.add(f, arcname=str(arc / f.relative_to(base)), recursive=False)
                count += 1
    return count


def _bundle(host, code: Path, dest: Path) -> str:
    """Write repo.bundle for code/ and verify it; returns a note ('' when it worked, why it was skipped otherwise)."""
    if not (code / ".git").exists():
        return "There is no git repo, so repo.bundle was skipped."
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
    steps += [f"{n}. Unpack the notes and untracked files into it: `tar -xzf files.tar.gz -C {folder}`"]
    n += 1
    steps += [f"{n}. Optional: put the build history back: `tar -xzf runs.tar.gz -C <Phoenix home>` "
              "(run folders go to runs/, work folders to work/)."]
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
    note = _bundle(host, folder / "code", dest / "repo.bundle")
    rels = _project_files(host, folder)
    stored = _write_tar(dest / "files.tar.gz", folder, rels)
    run_count = _write_runs_tar(dest / "runs.tar.gz", name)
    repo = plan_["repo"]
    has_bundle = (dest / "repo.bundle").is_file()
    manifest = {"name": name, "folder": str(folder), "repo": repo,
                "repo_url": project.repo_of(folder) or (f"https://github.com/{repo}" if repo else ""),
                "who": who, "when": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": sorted(p.name for p in dest.iterdir()) + ["manifest.json", "RESTORE.md"],
                "files_stored": stored, "run_files": run_count, "notes": [note] if note else [],
                "repo_delete": plan_["repo_delete"], "plan": plan_}
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


def _stop_chat(name: str, host) -> str:
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
    reasons = _refusals(name, who, _chat(name, adapters)["state"])
    if reasons:
        raise common.Conflict(" ".join(reasons))


def delete(name: str, confirm_name: str, who: str, adapters) -> dict:
    """Delete a project entirely after a safety copy; returns {name, backup, steps, not_done, still_live}."""
    folder = common.project_dir(name)
    _refuse(name, who, adapters)
    if confirm_name != name:
        raise common.OpsError(f"Type the project's name ({name}) to confirm. Nothing was deleted.")
    live = _deployments(name, folder)
    dest = backup(name, who, adapters)
    verdict = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["repo_delete"]
    repo = verdict["repo"]
    host = adapters.host
    steps, not_done = [], []
    common.record_command(who, f"project delete {name}: safety copy written to {dest}", name)

    def records() -> str:
        host.remove_tree(paths.runs(name))
        host.remove_tree(paths.home() / "work" / name)
        return "Removed Phoenix's records and runs for the project."

    def remove_folder() -> str:
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

    _step(steps, who, name, "records and runs", records)
    _step(steps, who, name, "chat unit", lambda: _stop_chat(name, host))
    _step(steps, who, name, "project folder", remove_folder)
    _step(steps, who, name, "saved keys", remove_keys)
    _step(steps, who, name, "folder trust", trust)
    _step(steps, who, name, "removed list and INDEX.md", lambda: _forget(name))
    _github_step(steps, not_done, who, name, verdict, host)
    events.emit("project.deleted", project=name, who=who, backup=str(dest), repo=repo)
    for s in steps:
        if not s["ok"] and s["step"] != "GitHub repo":
            not_done.append({"what": s["step"], "how": s["words"]})
    return {"name": name, "backup": str(dest), "steps": steps, "not_done": not_done, "still_live": live}


def _github_step(steps: list, not_done: list, who: str, name: str, verdict: dict, host) -> None:
    """Run the GitHub repo delete as a step; a refusal for lack of scope goes into not_done.

    A repo the verdict keeps (not this project's own, shared, not made by Phoenix) is never touched: the step
    is recorded as kept, with the reason."""
    repo = verdict.get("repo")
    if not verdict.get("delete"):
        steps.append({"step": "GitHub repo", "ok": True, "kept": True, "words": verdict.get("why") or "Kept."})
        common.record_command(who, f"project delete {name}: GitHub repo (kept)", name)
        return
    state = {}

    def run() -> str:
        ok, words, scope = _gh_delete(repo, host)
        state.update(ok=ok, scope=scope)
        if not ok:
            raise common.OpsError(words)
        return words
    _step(steps, who, name, "GitHub repo", run)
    if not steps[-1]["ok"]:
        how = ("Delete it on GitHub, or run `gh auth refresh -h github.com -s delete_repo` once in your own "
               "terminal and press Delete repo again." if state.get("scope") else steps[-1]["words"])
        not_done.append({"what": steps[-1]["words"] if state.get("scope") else f"GitHub repo {repo}", "how": how})


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
    """Retry only the GitHub repo delete, reading the repo from the newest safety copy's manifest."""
    if name in PROTECTED or who not in ALLOWED_CALLERS:
        raise common.Conflict(" ".join(_refusals(name, who, "off")))
    copy = _newest_copy(name)
    if copy is None:
        raise common.NotFound(f"There is no safety copy for '{name}', so Phoenix does not know its GitHub repo.")
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    verdict = manifest.get("repo_delete") or {"repo": manifest.get("repo"), "delete": False,
                                               "why": "This safety copy does not say the repo was Phoenix's own."}
    steps, not_done = [], []
    _github_step(steps, not_done, who, name, verdict, adapters.host)
    events.emit("project.changed", project=name, who=who, what="github repo deleted" if steps[0]["ok"] else "github repo kept")
    return {"name": name, "backup": str(copy), "steps": steps, "not_done": not_done}
