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


def _preset_steps(data: dict | None) -> dict:
    """{step name: on} for every step the preset file switches on or off."""
    tables = (data or {}).get("steps", {})
    return {name: bool(t["on"]) for name, t in tables.items() if isinstance(t, dict) and "on" in t}


CUSTOM_DESCRIPTION = "Start from a preset and switch any step on or off yourself."


def presets() -> dict:
    """The presets a project can choose, with their titles, one-line descriptions and the steps each switches on or off."""
    rows = []
    for name in settings.PRESETS:
        data = None
        if name != "custom":
            try:
                data = settings._read_layer(paths.library() / "presets" / f"{name}.toml", f"presets/{name}.toml")
            except settings.SettingsError:
                data = None
        rows.append({"name": name, "title": (data or {}).get("title", name.capitalize()),
                     "has_file": data is not None, "description": (data or {}).get("description", "") or (CUSTOM_DESCRIPTION if name == "custom" else ""),
                     "steps": _preset_steps(data)})
    return {"presets": rows}


def services() -> dict:
    """Every service in the services library with the project keys it needs."""
    from phoenix9 import services as core
    rows = [{"name": s["name"], "title": s["title"], "project_keys": s["project_keys"]}
            for s in sorted(core.load_library().values(), key=lambda s: s["name"])]
    return {"services": rows, "problems": core.load_problems()}


def tools() -> dict:
    """The Claude Code tools a step may be given or denied, each with a plain label and explanation."""
    from phoenix9 import claude
    return {"tools": [{"name": n, "label": label, "help": h} for n, label, h in claude.SUPPORTED_TOOLS]}
