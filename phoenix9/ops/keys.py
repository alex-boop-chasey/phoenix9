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
