"""Creating a project (proj folded in): folder, notes, code, settings, keys, repo, chat service; undo on failure."""
import json
import os
import re
import shlex
import shutil
import tomllib
from pathlib import Path

from phoenix9 import atomic, events, git, keys, paths, project_services, services, settings, templates
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
NOTES_SUBFOLDERS = ("research", "specs", "plans", "sessions")
RECIPE_TIMEOUT = 1800
START_CHECKS = 6
SAFE = git.SAFE


def claude_json() -> str:
    """Claude Code's own settings file (PHOENIX_CLAUDE_JSON, else /root/.claude.json)."""
    return os.environ.get("PHOENIX_CLAUDE_JSON") or "/root/.claude.json"


def unit(name: str) -> str:
    """The systemd unit that keeps a project's chat server on."""
    return f"claude-rc@{name}.service"


def _first_error(rc: int, out: str, err: str) -> str:
    """The first non-empty line of a failed command's output."""
    for text in (err, out):
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    return f"exit code {rc}"


def _run(host, what: str, argv: list, timeout: float = 120, cwd=None) -> str:
    """Run a host command; OpsError with the first error line when it fails. Returns stdout."""
    rc, out, err = host.run(argv, timeout=timeout, cwd=cwd) if cwd else host.run(argv, timeout=timeout)
    if rc != 0:
        raise OpsError(f"{what}: {_first_error(rc, out, err)}")
    return out


# ----------------------------------------------------------------------------- validation
def _read_keys_file(path) -> list[dict]:
    """The [[key]] rows of a keys file; OpsError in plain words when it is not usable."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as err:
        raise OpsError(f"Cannot read the keys file {path}: {err.strerror}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise OpsError(f"The keys file {path} is not valid TOML.") from None
    rows = data.get("key", [])
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("name"), str)
                                             and isinstance(r.get("value"), str) for r in rows):
        raise OpsError(f"The keys file {path} needs [[key]] rows with name, value and secret.")
    return rows


def _source(opts: dict) -> str:
    """Which source the form chose: repo, code, template or empty (exactly one allowed)."""
    chosen = [k for k in ("repo", "code", "template") if opts.get(k)]
    if len(chosen) > 1:
        raise OpsError("Choose only one of --repo, --code and --template.")
    return chosen[0] if chosen else "empty"


def _profile(opts: dict, tpl: dict | None) -> str:
    """The profile: the form's, else the menu template's; OpsError when unknown or missing."""
    profile = opts.get("profile") or (tpl["profile"] if tpl else "")
    if not profile:
        raise OpsError("Say which profile to use (--profile); there is no template to take it from.")
    lib = paths.library()
    if not (lib / "profiles" / profile / "profile.toml").is_file():
        known = sorted(p.name for p in (lib / "profiles").iterdir() if p.is_dir()) if (lib / "profiles").is_dir() else []
        raise OpsError(f"Unknown profile '{profile}'. Available: {', '.join(known) or 'none'}.")
    return profile


def validate(opts: dict, host) -> dict:
    """Check the whole form before anything is made; returns the facts create needs."""
    name = opts.get("name") or ""
    if not NAME_RE.match(name):
        raise OpsError(f"'{name}' is not a good project name: use lowercase letters, digits and dashes (up to 41).")
    if (paths.projects() / name).exists():
        raise OpsError(f"A project called '{name}' already exists.")
    source = _source(opts)
    tpl = None
    if source == "template":
        tpl = templates.get(opts["template"])
        if tpl is None and not REPO_RE.match(opts["template"]):
            names = ", ".join(t["name"] for t in templates.load_menu())
            raise OpsError(f"Unknown template '{opts['template']}'. Available: {names or 'none'}, or a GitHub OWNER/NAME.")
    profile = _profile(opts, tpl)
    lib = services.load_library()
    unknown = [s for s in opts.get("services") or [] if s not in lib]
    if unknown:
        raise OpsError(f"Unknown service: {', '.join(unknown)}. Available: {', '.join(sorted(lib)) or 'none'}.")
    if opts.get("code") and not Path(opts["code"]).is_dir():
        raise OpsError(f"--code: there is no folder {opts['code']}.")
    for repo in (opts.get("repo"), None if tpl or source != "template" else opts["template"]):
        if repo:
            if not REPO_RE.match(repo):
                raise OpsError(f"'{repo}' should look like OWNER/NAME.")
            rc, out, err = host.gh("repo", "view", repo, "--json", "name")
            if rc != 0:
                raise OpsError(f"Cannot see {repo} on GitHub: {_first_error(rc, out, err)}")
    new_repo = opts.get("new_repo")
    if source in ("empty", "template"):
        if bool(new_repo) == bool(opts.get("no_new_repo")):
            raise OpsError("Say whether to make a GitHub repo: --new-repo OWNER or --no-new-repo.")
        if new_repo and not OWNER_RE.match(new_repo):
            raise OpsError(f"'{new_repo}' is not a GitHub owner name.")
    elif new_repo:
        raise OpsError("--new-repo only applies to an empty project or a template.")
    if opts.get("keys_file"):
        _read_keys_file(opts["keys_file"])
    return {"source": source, "template": tpl, "profile": profile, "new_repo": new_repo}


# ----------------------------------------------------------------------------- the pieces
def _source_words(opts: dict, source: str) -> str:
    return {"empty": "an empty folder", "repo": f"GitHub repo {opts.get('repo')}",
            "code": f"code at {opts.get('code')}", "template": f"template {opts.get('template')}"}[source]


def _make_folders(folder: Path) -> None:
    notes = folder / "notes"
    notes.mkdir(parents=True)
    notes.chmod(0o700)
    for sub in NOTES_SUBFOLDERS:
        (notes / sub).mkdir()


def _fill(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _placeholders(opts: dict) -> dict:
    """Template placeholder values; the description is made safe to sit inside quotes."""
    name = opts["name"]
    desc = " ".join((opts.get("description") or f"{name}, a new project").split())
    return {"name": name, "module": name.replace("-", "_"), "description": desc.replace('"', "'").replace("\\", "/")}


def _copy_template(tpl: dict, code: Path, values: dict) -> None:
    """Copy templates/<name>/files/ into code/, filling placeholders in file names and text."""
    root = Path(tpl["folder"]) / "files"
    for src in sorted(root.rglob("*")):
        dst = code / _fill(str(src.relative_to(root)), values)
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            dst.write_text(_fill(src.read_text(encoding="utf-8"), values), encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(src, dst)
        shutil.copymode(src, dst)


def _run_recipe(host, tpl: dict, code: Path) -> None:
    for command in tpl["run"]:
        _run(host, f"Template step '{command}' failed", shlex.split(command), RECIPE_TIMEOUT, cwd=code)


def _first_commit(code: Path) -> None:
    """git init and the first commit of a fresh code/ folder."""
    git.git(code, "init", "-q", "-b", "main")
    git.commit(code, "Project created by Phoenix 9", {}, skip_env=True)


def _get_code(opts, facts, folder: Path, host, made: list) -> str:
    """Make code/ (or note where the code is); returns the repo name used ('' when none yet)."""
    code, source, tpl = folder / "code", facts["source"], facts["template"]
    if source == "repo":
        _run(host, f"Could not copy {opts['repo']} into code/", ["gh", "repo", "clone", opts["repo"], str(code), "--", "-q"])
        code.mkdir(exist_ok=True)
        return opts["repo"]
    if source == "code":
        return ""
    if source == "template" and tpl is None:        # a GitHub template repo
        return _from_github_template(opts, facts, code, host, made)
    code.mkdir()
    values = _placeholders(opts)
    if tpl and tpl["kind"] == "files":
        _copy_template(tpl, code, values)
    elif tpl:
        _run_recipe(host, tpl, code)
    return ""


def _from_github_template(opts, facts, code: Path, host, made: list) -> str:
    """Use a GitHub template repo: a new repo made from it, or a plain copy with its history dropped."""
    if facts["new_repo"]:
        full = f"{facts['new_repo']}/{opts['name']}"
        _run(host, f"Could not create GitHub repo {full}", ["gh", "repo", "create", full, "--private", "--template", opts["template"]])
        made.append(("repo", full))
        _run(host, f"Could not copy {full} into code/", ["gh", "repo", "clone", full, str(code), "--", "-q"])
        code.mkdir(exist_ok=True)
        return full
    _run(host, f"Could not copy {opts['template']} into code/", ["gh", "repo", "clone", opts["template"], str(code), "--", "-q"])
    code.mkdir(exist_ok=True)
    git.rmtree(code / ".git")
    return ""


def _make_repo(opts, facts, code: Path, host, made: list) -> str:
    """Create the private GitHub repo for a fresh code/, set origin, push; returns OWNER/NAME."""
    full = f"{facts['new_repo']}/{opts['name']}"
    _run(host, f"Could not create GitHub repo {full}", ["gh", "repo", "create", full, "--private"])
    made.append(("repo", full))
    git.git(code, "remote", "add", "origin", f"https://github.com/{full}.git")
    _run(host, f"Could not push to {full}", ["git", *SAFE, "-C", str(code), "push", "-u", "origin", "main"], 300)
    return full


def _claude_md(opts, facts, repo: str) -> str:
    name, tpl = opts["name"], facts["template"]
    where = opts["code"] if facts["source"] == "code" else "code/"
    services_line = ", ".join(opts.get("services") or []) or "none"
    template = opts["template"] if facts["source"] == "template" else "none"
    about = (opts.get("description") or "").strip() or f"{name}: a new project."
    return (f"# {name}\n\n{about}\n\n- Code: {where}\n- Repo: {repo or '(none yet)'}\n- Profile: {facts['profile']}\n"
            f"- Services: {services_line}\n- Template: {template}\n\n@notes/NOW.md\n")


def _write_notes(folder: Path, opts, facts, today: str) -> None:
    name = opts["name"]
    atomic.write_text(folder / "notes" / "NOW.md",
                      f"# Now ({name})\n\n- {today}: created {today} from {_source_words(opts, facts['source'])}; "
                      "next: first chat refines CLAUDE.md.\n")
    atomic.write_text(folder / "notes" / "decisions.md", f"# Decisions ({name})\n\n")
    atomic.write_text(folder / "notes" / "changelog.md",
                      f"# Changelog ({name})\n\nPlain-English log of every change, newest last: date · who (chat, "
                      "subagent, grunt, Phoenix) · what.\n\n")


def _add_decision(folder: Path, line: str) -> None:
    path = folder / "notes" / "decisions.md"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"- {common._today()}: {line}\n")


def _save_keys(name: str, keys_file: str, made: list) -> None:
    """Store the keys-file rows as the project's keys (values never printed)."""
    made.append(("keys", name))
    for row in _read_keys_file(keys_file):
        try:
            keys.set_key(name, row["name"], row["value"], bool(row.get("secret", True)))
        except keys.KeyError_ as err:
            raise OpsError(f"Keys file: {err}") from None


def _vscode_task(folder: Path, name: str) -> None:
    task = {"version": "2.0.0", "tasks": [{
        "label": f"Make sure {name} is on for the Claude app", "type": "shell",
        "command": f"phoenix project open {name}", "runOptions": {"runOn": "folderOpen"},
        "presentation": {"reveal": "silent", "panel": "dedicated", "close": True}, "problemMatcher": []}]}
    atomic.write_json(folder / ".vscode" / "tasks.json", task)


def trust(host, folder: Path) -> None:
    """Mark the folder (by its /srv/projects name and its real path) as trusted in Claude Code's settings."""
    path = claude_json()
    try:
        data = json.loads(host.read_text(path))
    except FileNotFoundError:
        data = {}
    except ValueError:
        raise OpsError(f"{path} is not valid JSON; cannot mark {folder} as trusted.") from None
    changed = False
    for where in {str(folder), os.path.realpath(folder)}:
        entry = data.setdefault("projects", {}).setdefault(where, {})
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            changed = True
    if changed:
        host.write_text(path, json.dumps(data, indent=2))


def switch_on(host, clock, name: str, folder: Path, made: list) -> None:
    """Enable and start the project's chat server, then watch the journal for errors (proj's `open`)."""
    u = unit(name)
    made.append(("service", name))
    host.systemctl("enable", "-q", u)
    trust(host, folder)
    rc, out, err = host.systemctl("start", u)
    if rc != 0:
        raise OpsError(f"Could not start {u}: {_first_error(rc, out, err)}")
    for _ in range(START_CHECKS):
        clock.sleep(1)
        bad = [x for x in host.journal(u).splitlines() if re.search(r"error|not trusted", x, re.I)]
        if bad:
            host.systemctl("stop", u)
            raise OpsError(f"{name} failed to start: {bad[-1].strip()}")
        if host.systemctl("is-active", "-q", u)[0] != 0:
            raise OpsError(f"{name} stopped straight away; see: journalctl -u {u}")


# ----------------------------------------------------------------------------- index and undo
def _index_line(name: str, where: str) -> str:
    return f"| {name} | {where or '-'} | (new) |"


def _add_index(line: str) -> None:
    path = paths.projects() / "INDEX.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not old or old.endswith("\n") else "\n"
    atomic.write_text(path, f"{old}{sep}{line}\n")


def _remove_index(line: str) -> None:
    path = paths.projects() / "INDEX.md"
    if not path.exists():
        return
    rows = path.read_text(encoding="utf-8").splitlines()
    if line in rows:
        rows.remove(line)
        atomic.write_text(path, "".join(r + "\n" for r in rows))


def undo(made: list, host) -> None:
    """Reverse what create made, newest first; a GitHub repo is never deleted."""
    for kind, value in reversed(made):
        try:
            if kind == "service":
                host.systemctl("stop", unit(value))
                host.systemctl("disable", "-q", unit(value))
            elif kind == "folder":
                git.rmtree(Path(value))
            elif kind == "keys":
                (paths.keys() / f"{value}.toml").unlink(missing_ok=True)
            elif kind == "index":
                _remove_index(value)
        except OSError:
            pass


def _left_in_place(made: list) -> str:
    repos = [v for k, v in made if k == "repo"]
    if not repos:
        return ""
    return f" GitHub repo {repos[0]} was created and left in place; delete it by hand if you don't want it."


# ----------------------------------------------------------------------------- create
def _build(opts, facts, adapters, who, folder: Path, made: list, say) -> dict:
    host, name, today = adapters.host, opts["name"], common._today()
    say("Making the folder and notes")
    made.append(("folder", str(folder)))
    _make_folders(folder)
    _write_notes(folder, opts, facts, today)
    say("Getting the code")
    repo = _get_code(opts, facts, folder, host, made)
    code = folder / "code"
    if facts["source"] in ("empty", "template") and not (code / ".git").exists():
        _first_commit(code)
    say("Writing CLAUDE.md")
    atomic.write_text(folder / "CLAUDE.md", _claude_md(opts, facts, repo or opts.get("repo") or ""))
    say("Writing phoenix.toml")
    settings.save_project(folder, {"preset": "quick", "profile": facts["profile"]})
    if opts.get("services"):
        project_services.set_services(name, list(opts["services"]), who)
    if opts.get("keys_file"):
        say("Saving keys")
        _save_keys(name, opts["keys_file"], made)
        keys.write_env_example(name)
    say("Recording project facts")
    tpl_name = opts["template"] if facts["source"] == "template" else None
    atomic.write_json(folder / ".phoenix" / "project.json", {
        "created": today, "who": who, "source": facts["source"], "template": tpl_name, "profile": facts["profile"],
        "repo": repo or opts.get("repo") or None, "code": opts["code"] if facts["source"] == "code" else "code/",
        "chat_session_url": None, "environment_id": None, "services_set_up": []})
    if facts["new_repo"] and facts["source"] in ("empty", "template") and not repo:
        say("Creating the GitHub repo")
        repo = _make_repo(opts, facts, code, host, made)
        project = json.loads((folder / ".phoenix" / "project.json").read_text(encoding="utf-8"))
        atomic.write_json(folder / ".phoenix" / "project.json", {**project, "repo": repo})
        atomic.write_text(folder / "CLAUDE.md", _claude_md(opts, facts, repo))
    _vscode_task(folder, name)
    if opts.get("chat", True):
        say("Switching the project chat on")
        switch_on(host, adapters.clock, name, folder, made)
    return {"repo": repo or opts.get("repo") or "", "today": today}


def create(opts: dict, adapters, who: str, progress=None) -> dict:
    """Make a new project from the form (project-setup spec section 6); undoes everything on failure."""
    steps: list[str] = []

    def say(line: str) -> None:
        steps.append(line)
        if progress:
            progress(line)

    say("Checking the form")
    facts = validate(opts, adapters.host)
    name = opts["name"]
    folder = paths.projects() / name
    made: list = []
    try:
        result = _build(opts, facts, adapters, who, folder, made, say)
        say("Adding it to the project list")
        line = _index_line(name, result["repo"] or (opts.get("code") or ""))
        _add_index(line)
        made.append(("index", line))
        words = f"created from template {opts['template']}, profile {facts['profile']}" if facts["source"] == "template" \
            else f"created from {_source_words(opts, facts['source'])}, profile {facts['profile']}"
        _add_decision(folder, words)
        events.emit("project.created", project=name, who=who, source=facts["source"], profile=facts["profile"],
                    template=opts.get("template") if facts["source"] == "template" else None)
        common.record_command(who, f"project new {name}", name, change=f"created by {who}")
    except Exception as err:
        left = _left_in_place(made)
        undo(made, adapters.host)
        message = str(err) if isinstance(err, OpsError) else f"{type(err).__name__}: {err}"
        raise OpsError(message.rstrip(".") + "." + left) from None
    return {"name": name, "path": str(folder), "source": facts["source"], "profile": facts["profile"],
            "template": opts.get("template") if facts["source"] == "template" else None,
            "repo": result["repo"] or None, "services": list(opts.get("services") or []), "steps": steps}
