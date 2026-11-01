"""Ops for the library: what steps, profiles and presets exist."""
from phoenix9 import paths, settings
from phoenix9.ops import common


def steps() -> dict:
    """Every working step, plus the problems found in broken ones."""
    lib = common.library()
    rows = [{"name": s.name, "title": s.title, "kind": s.kind, "group": s.group,
             "default": s.default, "description": s.description} for s in lib.steps]
    return {"steps": rows, "problems": list(lib.problems)}


def _folders(kind: str) -> list:
    root = paths.library() / kind
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def profiles() -> dict:
    """Every profile with its title and image tag, plus problems."""
    rows, problems = [], []
    lib = common.library()
    for folder in _folders("profiles"):
        try:
            data = settings.load_profile(paths.library(), folder.name)
        except settings.SettingsError as err:
            problems.append(str(err))
            continue
        rows.append({"name": folder.name, "title": data.get("title", folder.name),
                     "image": data.get("image", "")})
        problems += settings.check_profile(paths.library(), folder.name, lib)
    return {"profiles": rows, "problems": problems}


def presets() -> dict:
    """The presets a project can choose, with their titles."""
    rows = []
    for name in settings.PRESETS:
        try:
            data = settings.load_preset(paths.library(), name)
        except settings.SettingsError:
            data = None
        rows.append({"name": name, "title": (data or {}).get("title", name), "has_file": data is not None,
                     "description": (data or {}).get("description", "")})
    return {"presets": rows}


def services() -> dict:
    """Every service in the services library with the project keys it needs."""
    from phoenix9 import services as core
    rows = [{"name": s["name"], "title": s["title"], "project_keys": s["project_keys"]}
            for s in sorted(core.load_library().values(), key=lambda s: s["name"])]
    return {"services": rows, "problems": core.load_problems()}
