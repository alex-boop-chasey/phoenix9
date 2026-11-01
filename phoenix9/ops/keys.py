"""Ops for a project's keys: list (masked), set from a value read elsewhere, remove; and the keys audit."""
import os
import stat
from datetime import datetime, timezone

from phoenix9 import keys, paths, services, settings
from phoenix9.ops import common


def _guard(fn, *args):
    try:
        return fn(*args)
    except keys.KeyError_ as err:
        raise common.OpsError(str(err)) from None


def list_(project: str, who: str) -> list:
    """The project's keys without secret values."""
    common.project_dir(project)
    common.record_command(who, f"project keys {project}", project)
    return keys.list_keys(project)


def set_(project: str, name: str, value: str, secret: bool, who: str) -> dict:
    """Store a key; the command record has the name only."""
    common.project_dir(project)
    _guard(keys.set_key, project, name, value, secret)
    common.record_command(who, f"project keys {project} set {name}", project, change=f"key {name} set")
    return {"project": project, "name": name, "secret": secret}


def remove(project: str, name: str, who: str) -> dict:
    """Delete a key."""
    common.project_dir(project)
    if not keys.remove_key(project, name):
        raise common.OpsError(f"{project} has no key called {name}.")
    common.record_command(who, f"project keys {project} remove {name}", project, change=f"key {name} removed")
    return {"project": project, "name": name, "removed": True}


def rows(project: str) -> list:
    """The project's keys without secret values, and no command record (the dashboard polls this)."""
    common.project_dir(project)
    return keys.list_keys(project)


def _row_problems(project: str, rows) -> list:
    """Every problem in the rows to save, in plain words (empty when all are fine)."""
    saved = {r["name"]: r for r in keys.list_keys(project)}
    problems, seen = [], set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            problems.append(f"Row {i} is not a key.")
            continue
        name, value = row.get("name"), row.get("value")
        label = name if isinstance(name, str) and name else f"row {i}"
        if not isinstance(name, str) or not keys.NAME_RE.match(name):
            problems.append(f"'{name}' is not a good key name: use letters, digits and underscores, not starting with a digit.")
            continue
        if name in seen:
            problems.append(f"The name {name} appears more than once.")
        seen.add(name)
        if value is not None and not isinstance(value, str):
            problems.append(f"The value for {label} must be text.")
        elif isinstance(value, str) and ("\n" in value or "\r" in value):
            problems.append(f"The value for {label} has a line break, which an env file cannot hold.")
        elif not value and not (name in saved and saved[name]["has_value"]):
            problems.append(f"The value for {label} is empty.")
    return problems


def save(project: str, rows: list, who: str) -> list:
    """Check every row, then store them; a row without a value keeps its saved value. Returns the masked rows."""
    common.project_dir(project)
    if not isinstance(rows, list):
        raise common.OpsError("The keys should be a list of rows.")
    problems = _row_problems(project, rows)
    if problems:
        raise common.OpsError("Some keys cannot be saved:\n" + "\n".join(f"- {p}" for p in problems))
    names = []
    for row in rows:
        secret = bool(row.get("secret", True))
        if row.get("value"):
            _guard(keys.set_key, project, row["name"], row["value"], secret)
        else:
            keys.set_secret_flag(project, row["name"], secret)
        names.append(row["name"])
    common.record_command(who, f"project keys {project} save {' '.join(names)}", project,
                          change=f"keys saved: {', '.join(names) or 'none'}")
    return keys.list_keys(project)


def reveal(project: str, name: str, who: str) -> dict:
    """The one place a saved value leaves the server; the command record has the name only."""
    common.project_dir(project)
    value = keys.get_value(project, name) if isinstance(name, str) else None
    if value is None:
        raise common.NotFound(f"{project} has no key called {name}.")
    common.record_command(who, f"project keys {project} reveal {name}", project)
    return {"name": name, "value": value}


# ---------- keys audit: names, modes and problems; never a value ----------
FIXED_USES = {"claude.env": "step containers' Claude token",
              "github.env": "github service; Merge's host login note",
              "telegram.env": "notify (Telegram)"}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _file_use(file_name: str, library: dict) -> tuple[str, str | None]:
    """(what reads this secrets file, the unknown service name or None)."""
    if file_name in FIXED_USES:
        return FIXED_USES[file_name], None
    if file_name.startswith("service-"):
        svc = file_name[len("service-"):-len(".env")]
        for name, entry in library.items():
            if entry["secrets_file"] == file_name:
                return f"{name} service proxy", None
        return f"{svc} service proxy", svc
    return "nothing known", None


def _global_rows(library: dict, problems: list) -> list:
    """One row per secrets file."""
    rows = []
    for item in keys.secret_files():
        use, unknown = _file_use(item["file"], library)
        mode = _mode(paths.secrets() / item["file"])
        if mode & 0o077:
            problems.append(f"{item['file']} can be read by other users (mode {mode:o}); run chmod 600 on it.")
        if unknown is not None:
            problems.append(f"{item['file']} is for '{unknown}', which is not in the services library.")
        rows.append({"file": item["file"], "names": item["names"], "used_by": use,
                     "modified": _iso(item["modified"]), "mode": f"{mode:04o}", "mode_ok": mode == 0o600})
    return rows


def _project_services(project: str) -> list:
    try:
        return list(settings.load_project(paths.projects() / project).get("services", []))
    except (settings.SettingsError, OSError):
        return []


def _expected(project: str, library: dict) -> dict:
    """{key name: service name} for the keys the project's services expect."""
    out = {}
    for name in _project_services(project):
        for k in (library.get(name) or {}).get("project_keys", []):
            out.setdefault(k["name"], name)
    return out


def _project_rows(library: dict, problems: list) -> list:
    """One row per key in each project keys file; missing expected service keys become problems."""
    rows = []
    folder = paths.keys()
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        project = path.stem
        mode = _mode(path)
        if mode & 0o077:
            problems.append(f"The keys file for {project} can be read by other users (mode {mode:o}); run chmod 600 on it.")
        touched = _iso(path.stat().st_mtime)
        expected = _expected(project, library)
        have = {}
        for k in keys.list_keys(project):
            have[k["name"]] = k["has_value"]
            use = "step containers as env var" + ("" if k["secret"] else ", .env.example")
            rows.append({"project": project, "name": k["name"], "secret": k["secret"], "set": k["has_value"],
                         "used": use, "last_touched": touched, "service": expected.get(k["name"], "")})
        for name, svc in expected.items():
            if not have.get(name):
                problems.append(f"{project}: {svc} expects {name}, which has no value.")
    for project in sorted(d.name for d in (paths.projects().iterdir() if paths.projects().is_dir() else [])):
        if not (folder / f"{project}.toml").is_file():
            for name, svc in _expected(project, library).items():
                problems.append(f"{project}: {svc} expects {name}, which has no value.")
    return rows


def _account_problems(library: dict, global_rows: list, problems: list) -> None:
    """A connected service whose secrets file lacks one of its account keys."""
    by_file = {r["file"]: r for r in global_rows}
    for name, entry in services.read_registry().items():
        svc = library.get(name)
        if svc is None or not entry.get("connected"):
            continue
        row = by_file.get(svc["secrets_file"])
        have = row["names"] if row else []
        for key in svc["account_keys"]:
            if key not in have:
                problems.append(f"{svc['title']} is connected but {svc['secrets_file']} has no {key}.")


def audit() -> dict:
    """Every secrets file and project key (names, modes, times) plus problems; never a value."""
    library = services.load_library()
    problems: list = []
    global_rows = _global_rows(library, problems)
    _account_problems(library, global_rows, problems)
    return {"global": global_rows, "projects": _project_rows(library, problems), "problems": problems}
