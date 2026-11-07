"""Creating a project (proj folded in): folder, notes, code, settings, keys, repo; undo on failure."""
import json
import os
import re
import shlex
import shutil
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, events, gates, git, keys, paths, project_services, projectchat, runs, services, settings, templates
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
NOTES_SUBFOLDERS = ("research", "specs", "plans", "sessions")
RECIPE_TIMEOUT = 1800
SIZE_MAX_AGE = 300
SIZE_WAIT = 1.0
HOME_PROJECT = "home"
SAFE = git.SAFE


def claude_json() -> str:
    """Claude Code's own settings file (PHOENIX_CLAUDE_JSON, else /root/.claude.json)."""
    return os.environ.get("PHOENIX_CLAUDE_JSON") or "/root/.claude.json"


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
    """The profile: the form's, else the menu template's, else "" (none yet); OpsError when unknown."""
    profile = opts.get("profile") or (tpl["profile"] if tpl else "")
    if not profile:
        return ""
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
    for row in opts.get("keys") or []:
        if not (isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("value"), str)):
            raise OpsError("Each key needs a name and a value.")
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


PROFILE_ECOSYSTEMS = {"web": ("npm",), "mobile": ("npm",), "platform": ("npm",), "desktop": ("npm", "cargo"), "python-script": ("pip",)}
FILE_ECOSYSTEMS = (("package.json", "npm"), ("Cargo.toml", "cargo"), ("pyproject.toml", "pip"), ("requirements.txt", "pip"))


def _dependabot_ecosystems(code: Path, profile: str) -> list[str]:
    """Package ecosystems for Dependabot: from the files in code/, else from the profile."""
    found = [eco for file, eco in FILE_ECOSYSTEMS if (code / file).is_file()]
    return list(dict.fromkeys(found or PROFILE_ECOSYSTEMS.get(profile, ())))


def _write_dependabot(code: Path, profile: str) -> None:
    """Write .github/dependabot.yml for a repo Phoenix is creating (nothing when no ecosystem is known)."""
    ecosystems = _dependabot_ecosystems(code, profile)
    if not ecosystems:
        return
    entries = "".join(f'  - package-ecosystem: "{eco}"\n    directory: "/"\n    schedule:\n      interval: "weekly"\n'
                      f'    open-pull-requests-limit: 5\n' for eco in ecosystems)
    atomic.write_text(code / ".github" / "dependabot.yml", f"version: 2\nupdates:\n{entries}")


def _get_code(opts, facts, folder: Path, host, made: list, say) -> str:
    """Make code/ (or note where the code is); returns the repo name used ('' when none yet)."""
    code, source, tpl = folder / "code", facts["source"], facts["template"]
    if source == "repo":
        _run(host, f"Could not copy {opts['repo']} into code/", ["gh", "repo", "clone", opts["repo"], str(code), "--", "-q"])
        code.mkdir(exist_ok=True)
        return opts["repo"]
    if source == "code":
        return ""
    if source == "template" and tpl is None:        # a GitHub template repo
        return _from_github_template(opts, facts, code, host, made, say)
    code.mkdir()
    values = _placeholders(opts)
    if tpl and tpl["kind"] == "files":
        _copy_template(tpl, code, values)
    elif tpl:
        _run_recipe(host, tpl, code)
    return ""


def _from_github_template(opts, facts, code: Path, host, made: list, say) -> str:
    """Use a GitHub template repo: a new repo made from it, or a plain copy with its history dropped."""
    if facts["new_repo"]:
        full = f"{facts['new_repo']}/{opts['name']}"
        _run(host, f"Could not create GitHub repo {full}", ["gh", "repo", "create", full, "--private", "--template", opts["template"]])
        made.append(("repo", full))
        _auto_delete_branches(host, full, say)
        _run(host, f"Could not copy {full} into code/", ["gh", "repo", "clone", full, str(code), "--", "-q"])
        code.mkdir(exist_ok=True)
        return full
    _run(host, f"Could not copy {opts['template']} into code/", ["gh", "repo", "clone", opts["template"], str(code), "--", "-q"])
    code.mkdir(exist_ok=True)
    git.rmtree(code / ".git")
    return ""


def _auto_delete_branches(host, full: str, warn) -> None:
    """Switch on GitHub's "delete head branches after merge" for the repo; a failure is only a warning."""
    rc, out, err = host.gh("repo", "edit", full, "--delete-branch-on-merge")
    if rc != 0:
        warn(f"Warning: could not switch on automatic branch clean-up on GitHub: {_first_error(rc, out, err)}")


def _make_repo(opts, facts, code: Path, host, made: list, say) -> str:
    """Create the private GitHub repo for a fresh code/, set origin, push; returns OWNER/NAME."""
    full = f"{facts['new_repo']}/{opts['name']}"
    _run(host, f"Could not create GitHub repo {full}", ["gh", "repo", "create", full, "--private"])
    made.append(("repo", full))
    _auto_delete_branches(host, full, say)
    git.git(code, "remote", "add", "origin", f"https://github.com/{full}.git")
    _run(host, f"Could not push to {full}", ["git", *SAFE, "-C", str(code), "push", "-u", "origin", "main"], 300)
    return full


def _repo_id(host, full: str) -> str | None:
    """GitHub's id for the repo OWNER/NAME (None when GitHub does not say, or names another repo)."""
    rc, out, _ = host.gh("repo", "view", full, "--json", "id,nameWithOwner")
    try:
        data = json.loads(out) if rc == 0 else {}
    except ValueError:
        return None
    if not isinstance(data, dict) or str(data.get("nameWithOwner", "")).lower() != full.lower():
        return None
    return str(data["id"]) if data.get("id") else None


MADE_REPO_FIELDS = ("phoenix_made_repo", "phoenix_made_repo_id")


def forget_made_repo(folder: Path) -> None:
    """Drop the record that Phoenix created the project's GitHub repo (after the repo is changed or imported)."""
    meta = _meta(folder)
    if any(k in meta for k in MADE_REPO_FIELDS):
        atomic.write_json(_meta_file(folder), {k: v for k, v in meta.items() if k not in MADE_REPO_FIELDS})


def _claude_md(opts, facts, repo: str) -> str:
    name, tpl = opts["name"], facts["template"]
    where = opts["code"] if facts["source"] == "code" else "code/"
    services_line = ", ".join(opts.get("services") or []) or "none"
    template = opts["template"] if facts["source"] == "template" else "none"
    about = (opts.get("description") or "").strip() or f"{name}: a new project."
    return (f"# {name}\n\n{about}\n\n- Code: {where}\n- Repo: {repo or '(none yet)'}\n- Profile: {facts['profile'] or '(not set yet)'}\n"
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


def _save_key_rows(name: str, rows: list, made: list) -> None:
    """Store {name, value, secret} rows from the form as the project's keys (values never printed)."""
    made.append(("keys", name))
    for row in rows:
        try:
            keys.set_key(name, row["name"], row["value"], bool(row.get("secret", True)))
        except keys.KeyError_ as err:
            raise OpsError(f"Keys: {err}") from None


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
            if kind == "folder":
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
    repo = _get_code(opts, facts, folder, host, made, say)
    code = folder / "code"
    if facts["source"] in ("empty", "template") and not (code / ".git").exists():
        if facts["new_repo"] and not repo:
            _write_dependabot(code, facts["profile"])
        _first_commit(code)
    say("Writing CLAUDE.md")
    atomic.write_text(folder / "CLAUDE.md", _claude_md(opts, facts, repo or opts.get("repo") or ""))
    if facts["profile"]:
        say("Writing phoenix.toml")
        settings.save_project(folder, {"profile": facts["profile"]})
    if opts.get("services"):
        project_services.set_services(name, list(opts["services"]), who)
    if opts.get("keys_file") or opts.get("keys"):
        say("Saving keys")
        if opts.get("keys_file"):
            _save_keys(name, opts["keys_file"], made)
        if opts.get("keys"):
            _save_key_rows(name, opts["keys"], made)
        keys.write_env_example(name)
    say("Recording project facts")
    tpl_name = opts["template"] if facts["source"] == "template" else None
    atomic.write_json(folder / ".phoenix" / "project.json", {
        "created": today, "who": who, "source": facts["source"], "template": tpl_name, "profile": facts["profile"],
        "repo": repo or opts.get("repo") or None, "code": opts["code"] if facts["source"] == "code" else "code/",
        "services_set_up": []})
    made_here = repo if facts["source"] == "template" and facts["template"] is None and facts["new_repo"] else ""
    if facts["new_repo"] and facts["source"] in ("empty", "template") and not repo:
        say("Creating the GitHub repo")
        repo = made_here = _make_repo(opts, facts, code, host, made, say)
        project = json.loads((folder / ".phoenix" / "project.json").read_text(encoding="utf-8"))
        atomic.write_json(folder / ".phoenix" / "project.json", {**project, "repo": repo})
        atomic.write_text(folder / "CLAUDE.md", _claude_md(opts, facts, repo))
    if made_here:      # only a repo Phoenix itself just created may ever be deleted with the project
        _save_meta(folder, phoenix_made_repo=made_here, phoenix_made_repo_id=_repo_id(host, made_here))
    trust(host, folder)
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
        kind = f", profile {facts['profile']}" if facts["profile"] else ""
        words = f"created from template {opts['template']}{kind}" if facts["source"] == "template" \
            else f"created from {_source_words(opts, facts['source'])}{kind}"
        _add_decision(folder, words)
        events.emit("project.created", project=name, who=who, source=facts["source"], profile=facts["profile"],
                    template=opts.get("template") if facts["source"] == "template" else None)
        common.record_command(who, f"project new {name}", name, change=f"created by {who}")
        chat_result = projectchat.set_up(name, adapters, who, say)
    except Exception as err:
        left = _left_in_place(made)
        undo(made, adapters.host)
        message = str(err) if isinstance(err, OpsError) else f"{type(err).__name__}: {err}"
        raise OpsError(message.rstrip(".") + "." + left) from None
    return {"name": name, "path": str(folder), "source": facts["source"], "profile": facts["profile"],
            "template": opts.get("template") if facts["source"] == "template" else None,
            "repo": result["repo"] or None, "services": list(opts.get("services") or []), "steps": steps,
            **chat_result}


# ----------------------------------------------------------------------------- reading a project
def _meta_file(folder: Path) -> Path:
    return folder / ".phoenix" / "project.json"


def _meta(folder: Path) -> dict:
    """The project's .phoenix/project.json as a dict ({} when missing or broken)."""
    try:
        data = json.loads(_meta_file(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_meta(folder: Path, **fields) -> None:
    """Merge fields into project.json."""
    atomic.write_json(_meta_file(folder), {**_meta(folder), **fields})


def _description_block(text: str):
    """(index, lines) of the description paragraph of a CLAUDE.md split on blank lines, or None."""
    blocks = text.split("\n\n")
    for i, block in enumerate(blocks):
        lines = [x.strip() for x in block.splitlines() if x.strip() and not x.lstrip().startswith("#")]
        if lines:
            return blocks, i, lines
    return None


def description(folder: Path) -> str:
    """The first paragraph of the project's CLAUDE.md (heading lines skipped)."""
    try:
        text = (folder / "CLAUDE.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    found = _description_block(text)
    return " ".join(found[2]) if found else ""


def repo_of(folder: Path) -> str:
    """The repo from project.json, else the git remote of code/, else ''."""
    recorded = _meta(folder).get("repo")
    if recorded:
        return str(recorded)
    code = folder / "code"
    return git.remote_url(code) if code.is_dir() else ""


def split_repo(repo: str) -> dict:
    """{owner, name} from OWNER/NAME or a GitHub URL; both None when it is not a GitHub repo."""
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", repo or "")
    if not m and REPO_RE.match(repo or ""):
        m = re.match(r"([^/]+)/([^/]+?)(?:\.git)?$", repo)
    return {"owner": m.group(1), "name": m.group(2)} if m else {"owner": None, "name": None}


def profile_of(folder: Path) -> str:
    """The project's profile (phoenix.toml, else project.json)."""
    try:
        own = settings.load_project(folder).get("profile")
    except settings.SettingsError:
        own = None
    return str(own or _meta(folder).get("profile") or "")


def _services_of(folder: Path) -> list:
    try:
        return list(settings.load_project(folder).get("services", []))
    except settings.SettingsError:
        return []


# ----------------------------------------------------------------------------- size
def _read_sizes() -> dict:
    data = atomic.read_json(paths.cache() / "sizes.json", {})
    return data if isinstance(data, dict) else {}


def cached_size(name: str, now: float | None = None, max_age: float | None = None):
    """The cached size in bytes, or None when missing (or older than max_age when given)."""
    entry = _read_sizes().get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("bytes"), int):
        return None
    if max_age is not None and (now or 0) - float(entry.get("at", 0)) > max_age:
        return None
    return entry["bytes"]


def size(name: str, adapters) -> int:
    """The project's folder size in bytes: the cache when under 5 minutes old, else measured with du."""
    now = adapters.clock.now()
    fresh = cached_size(name, now, SIZE_MAX_AGE)
    if fresh is not None:
        return fresh
    value = adapters.host.du_bytes(paths.projects() / name)
    sizes = _read_sizes()
    sizes[name] = {"bytes": value, "at": now}
    atomic.write_json(paths.cache() / "sizes.json", sizes)
    return value


# ----------------------------------------------------------------------------- VS Code link and last used
def vscode_link(name: str) -> dict:
    """{url, reason}: the VS Code link for /srv/projects/<name> (from the vscode_url global setting), or url null
    with the reason when the VS Code address is not set or the folder is missing."""
    from phoenix9 import addresses
    base = addresses.read()["vscode_url"]
    if not base:
        return {"url": None, "reason": addresses.VSCODE_NOT_SET}
    folder = paths.projects() / name
    if not folder.is_dir():
        return {"url": None, "reason": f"The folder {folder} does not exist."}
    return {"url": f"{base.rstrip('/')}/?folder={folder}", "reason": None}


def _used_file(name: str) -> Path:
    return paths.projects() / name / ".phoenix" / "last-used"


def mark_used(name: str) -> None:
    """Remember that the project was used just now (e.g. imported)."""
    path = _used_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def last_used(name: str, now: float):
    """(seconds-since-epoch or None, '3h ago' style words or 'never'); counts Phoenix's and the `proj` tool's
    records and the last change of any of the project's runs (run activity counts as use)."""
    stamps = []
    runs_dir = paths.runs(name)
    states = list(runs_dir.glob("*/state.json")) if runs_dir.is_dir() else []
    for path in (_used_file(name), paths.projects() / ".proj" / f"{name}.used", *states):
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            continue
    if not stamps:
        return None, "never"
    at = max(stamps)
    secs = max(0, int(now - at))
    if secs < 3600:
        words = f"{secs // 60}m ago"
    elif secs < 172800:
        words = f"{secs // 3600}h ago"
    else:
        words = f"{secs // 86400}d ago"
    return at, words


def harness_status(name: str) -> str:
    """The harness column in words (idle, queued, 'running task N of M', 'needs you', ...), from status.project_state."""
    from phoenix9 import status
    return status.project_state(name)["harness"]


# ----------------------------------------------------------------------------- info and list
def info(name: str, adapters, size_wait: bool = True) -> dict:
    """Everything known about one project; size is measured (or cached) unless size_wait is False."""
    folder = paths.projects() / name
    repo = repo_of(folder)
    at, words = last_used(name, adapters.clock.now())
    nbytes = size(name, adapters) if size_wait else cached_size(name)
    return {"name": name, "description": description(folder), "path": str(folder), "repo": repo,
            "repo_owner": split_repo(repo)["owner"], "repo_name": split_repo(repo)["name"],
            "profile": profile_of(folder), "services": _services_of(folder), "size": nbytes,
            "vscode_url": vscode_link(name)["url"], "vscode": vscode_link(name), "last_used": words, "last_used_at": at, "harness": harness_status(name),
            "has_phoenix_toml": (folder / "phoenix.toml").is_file()}


def project_names() -> list:
    """Every folder in the projects folder that has a CLAUDE.md (proj's rule), by name."""
    root = paths.projects()
    if not root.is_dir():
        return []
    from phoenix9 import project_removal
    gone = project_removal.removed_names()
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "CLAUDE.md").is_file() and p.name not in gone)


def _refresh_sizes(names: list, adapters) -> None:
    for n in names:
        size(n, adapters)


def list_projects(adapters, wait: float = SIZE_WAIT, names: list | None = None) -> list:
    """info for every project (or just `names`); sizes come from the cache, missing ones load in the background."""
    names = project_names() if names is None else names
    now = adapters.clock.now()
    stale = [n for n in names if cached_size(n, now, SIZE_MAX_AGE) is None]
    workers = [threading.Thread(target=_refresh_sizes, args=(stale, adapters), daemon=True)] if stale else []
    for w in workers:
        w.start()
    deadline = time.monotonic() + wait
    for w in workers:
        w.join(max(0.0, deadline - time.monotonic()))
    return [info(n, adapters, size_wait=False) for n in names]


def setup_facts(folder: Path) -> dict:
    """What was chosen at setup: kind (profile), source, template, preset, merge rule, created date."""
    meta = _meta(folder)
    try:
        own = settings.load_project(folder)
    except settings.SettingsError:
        own = {}
    return {"kind": profile_of(folder), "source": meta.get("source") or _guess_source(folder),
            "template": meta.get("template") or None,
            "preset": own.get("preset") or None, "merge": own.get("merge") or None,
            "created": meta.get("created") or _guess_created(folder), "services_set_up": _set_up_entries(meta),
            "waiting_for_keys": waiting_for_keys(folder.name)}


def _guess_created(folder: Path) -> str | None:
    """When setup did not record it: the date of the first commit in code/, else the folder's date."""
    code = folder / "code"
    if (code / ".git").exists():
        try:
            dates = git.git(code, "log", "--reverse", "--format=%cs", check=False).split()
            if dates:
                return dates[0]
        except (git.GitError, OSError):
            pass
    try:
        return datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return None


def _guess_source(folder: Path) -> str:
    """When setup did not record it: 'repo' (code/ has a GitHub origin), 'code' (code/ is a git repo) or 'empty'."""
    code = folder / "code"
    if not (code / ".git").exists():
        return "empty"
    return "repo" if git.remote_url(code) else "code"


def waiting_for_keys(name: str) -> list:
    """Titles of services built without their keys that still have a required key with no value."""
    from phoenix9 import keys
    entries = _meta(paths.projects() / name).get("services_deferred") or []
    if not entries:
        return []
    have = {k["name"]: k["has_value"] for k in keys.list_keys(name)}
    return [e["title"] for e in entries if any(not have.get(k) for k in e.get("keys") or [])]


def _set_up_entries(meta: dict) -> list:
    """services_set_up as {name, at, run, run_name} dicts (older plain-name entries get empty fields)."""
    out = []
    for e in meta.get("services_set_up") or []:
        e = e if isinstance(e, dict) else {"name": e}
        out.append({"name": e.get("name") or "", "at": e.get("at") or None, "run": e.get("run") or None,
                    "run_name": e.get("run_name") or None})
    return out


def show_project(name: str, adapters) -> dict:
    """info plus the setup facts, the last changelog lines and the open gates."""
    data = info(name, adapters)
    data["setup"] = setup_facts(paths.projects() / name)
    try:
        lines = (paths.projects() / name / "notes" / "changelog.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    data["changelog"] = [x for x in lines if x.startswith("- ")][-10:]
    data["gates"] = [{"id": g["id"], "kind": g.get("kind"), "title": g.get("title")} for g in gates.list_gates(name)]
    return data


# ----------------------------------------------------------------------------- edit
def _set_line(text: str, label: str, value: str) -> str:
    """Replace a '- Label: value' line of CLAUDE.md when it exists."""
    return re.sub(rf"(?m)^- {label}: .*$", lambda _m: f"- {label}: {value}", text, count=1)


def _rewrite_description(folder: Path, text: str) -> None:
    """Replace only the description paragraph of CLAUDE.md."""
    path = folder / "CLAUDE.md"
    old = path.read_text(encoding="utf-8")
    found = _description_block(old)
    if found:
        blocks, i, _ = found
        keep = [x for x in blocks[i].splitlines() if x.lstrip().startswith("#")]
        blocks[i] = "\n".join([*keep, text.strip()])
    else:
        blocks = [old.rstrip("\n"), text.strip() + "\n"]
    atomic.write_text(path, "\n\n".join(blocks))


def _set_origin(host, folder: Path, repo: str) -> None:
    """Point origin in code/ at the GitHub repo (add it when there is none)."""
    code = folder / "code"
    if not code.is_dir():
        return
    url = f"https://github.com/{repo}.git"
    has = host.run(["git", *SAFE, "-C", str(code), "remote", "get-url", "origin"])[0] == 0
    verb = ["remote", "set-url", "origin"] if has else ["remote", "add", "origin"]
    _run(host, "Could not set origin", ["git", *SAFE, "-C", str(code), *verb, url])


def edit(name: str, adapters, who: str, description_text=None, profile=None, repo=None) -> dict:
    """Change a project's description, profile or repo; checks everything before changing anything."""
    folder = paths.projects() / name
    if description_text is None and profile is None and repo is None:
        raise OpsError("Nothing to change: give --description, --profile or --repo.")
    if description_text is not None and not description_text.strip():
        raise OpsError("The description cannot be empty.")
    if profile is not None:
        if not profile:
            raise OpsError("Say which profile to use.")
        _profile({"profile": profile}, None)
    if repo is not None:
        if not REPO_RE.match(repo):
            raise OpsError(f"'{repo}' should look like OWNER/NAME.")
        rc, out, err = adapters.host.gh("repo", "view", repo, "--json", "name")
        if rc != 0:
            raise OpsError(f"Cannot see {repo} on GitHub: {_first_error(rc, out, err)}")
    changed = []
    if description_text is not None:
        _rewrite_description(folder, description_text)
        changed.append("description")
    if profile is not None:
        data = settings.load_project(folder)
        data["profile"] = profile
        settings.save_project(folder, data)
        _save_meta(folder, profile=profile)
        _edit_line(folder, "Profile", profile)
        changed.append(f"profile to {profile}")
    if repo is not None:
        _set_origin(adapters.host, folder, repo)
        _save_meta(folder, repo=repo)
        forget_made_repo(folder)       # whatever repo it is now, Phoenix did not create it
        _edit_line(folder, "Repo", repo)
        changed.append(f"repo to {repo}")
    events.emit("project.changed", project=name, who=who, what="edit", fields=changed)
    common.record_command(who, f"project edit {name}", name, change=f"changed {', '.join(changed)}")
    return {"project": name, "changed": changed}


def _edit_line(folder: Path, label: str, value: str) -> None:
    path = folder / "CLAUDE.md"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        new = _set_line(text, label, value)
        if new != text:
            atomic.write_text(path, new)
