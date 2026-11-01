"""The services library: services/<name>/service.toml (which project keys and hosts each service needs)."""
from phoenix9 import library, paths
from phoenix9.library import Field

FIELDS = [Field("name", str, required=True), Field("title", str, required=True),
          Field("project_keys", list, default=[], list_of=dict), Field("hosts", list, default=[], list_of=str)]
KEY_FIELDS = [Field("name", str, required=True), Field("secret", bool, default=True)]


def _parse(data: dict, folder, where: str):
    """Check one service.toml; returns (service dict or None, problems)."""
    values, problems = library.check_fields(data, FIELDS, where)
    if values["name"] != folder.name:
        problems.append(f"{where}: name '{values['name']}' must match the folder name '{folder.name}'")
    keys = []
    if not problems:
        for item in values["project_keys"]:
            key, bad = library.check_fields(item, KEY_FIELDS, f"{where} project_keys")
            problems += bad
            keys.append(key)
    values["project_keys"] = keys
    return (None if problems else values), problems


def load_library() -> dict:
    """Every service by name; a broken service.toml is left out (see load_problems)."""
    return {s["name"]: s for s in library.load_folders(paths.library() / "services", "service.toml", _parse)[0]}


def load_problems() -> list[str]:
    """Plain-words problems found in the services folder."""
    return library.load_folders(paths.library() / "services", "service.toml", _parse)[1]


def get(name: str) -> dict | None:
    """One service, or None when the library has none by that name."""
    return load_library().get(name)
