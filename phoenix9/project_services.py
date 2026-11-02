"""Choose a project's services: phoenix.toml, empty key rows, allowed hosts, decisions and changelog."""
from phoenix9 import atomic, keys, services, settings
from phoenix9.ops import common


def _hosts(names, lib) -> list[str]:
    return [h for n in names for h in lib[n]["hosts"]]


def chosen(project: str) -> list[str]:
    """The services listed in the project's phoenix.toml."""
    return list(settings.load_project(common.project_dir(project)).get("services", []))


def _decision(folder, names, lib, who) -> None:
    """Append '<date>: uses A and B (chosen by who)' to notes/decisions.md."""
    titles = [lib[n]["title"] for n in names] or ["no services"]
    words = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]
    path = folder / "notes" / "decisions.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not old or old.endswith("\n") else "\n"
    atomic.write_text(path, f"{old}{sep}- {common._today()}: uses {words} (chosen by {who})\n")


def set_services(project: str, names: list[str], who: str) -> dict:
    """Make `names` the project's services; adds empty key rows and hosts, never deletes keys."""
    lib = services.load_library()
    names = list(dict.fromkeys(names))
    unknown = [n for n in names if n not in lib]
    if unknown:
        raise common.OpsError(f"Unknown service: {', '.join(unknown)}. Available: {', '.join(sorted(lib)) or 'none'}.")
    folder = common.project_dir(project)
    data = settings.load_project(folder)
    old = [n for n in data.get("services", []) if n in lib]
    still_needed = set(_hosts(names, lib))
    gone = set(_hosts([n for n in old if n not in names], lib)) - still_needed
    allow = [h for h in data.get("domains", {}).get("allow", []) if h not in gone]
    allow += [h for h in _hosts(names, lib) if h not in allow]
    data["services"] = names
    data.setdefault("domains", {})["allow"] = allow
    settings.save_project(folder, data)
    for n in names:
        for key in lib[n]["project_keys"]:
            keys.add_empty(project, key["name"], key["secret"])
    _decision(folder, names, lib, who)
    common.record_command(who, f"project services {project} --set {','.join(names)}", project,
                          change=f"services set to {', '.join(names) or 'none'}")
    return {"project": project, "services": names, "hosts": allow}


def overview(project: str) -> dict:
    """The chosen services and the ones available."""
    lib = services.load_library()
    return {"project": project, "chosen": chosen(project),
            "available": [{"name": n, "title": s["title"]} for n, s in sorted(lib.items())]}
