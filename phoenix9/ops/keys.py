"""Ops for a project's keys: list (masked), set from a value read elsewhere, remove."""
from phoenix9 import keys
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
