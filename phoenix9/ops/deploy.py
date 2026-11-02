"""Ops for deploys: deploy now, deploy status and the deployers list."""
from pathlib import Path

from phoenix9 import deploy, paths
from phoenix9.ops import common

RECENT = 5


def _suggested() -> dict:
    """{deployer name: [profiles whose suggested_deployer it is]}."""
    from phoenix9 import settings
    found: dict = {}
    root = paths.library() / "profiles"
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        try:
            name = settings.load_profile(paths.library(), folder.name).get("suggested_deployer", "none")
        except settings.SettingsError:
            continue
        found.setdefault(name, []).append(folder.name)
    return found


def deployers() -> dict:
    """Every deployer: name, title, supported, preview, and the profiles that suggest it."""
    suggested = _suggested()
    order = {"none": 0}
    rows = [{"name": d["name"], "title": d["title"], "description": d["description"], "supported": d["supported"],
             "preview": d["preview"], "for_profiles": list(d["for_profiles"]),
             "suggested_for": suggested.get(d["name"], [])}
            for d in sorted(deploy.load_library().values(), key=lambda d: (order.get(d["name"], 1), d["name"]))]
    return {"deployers": rows, "problems": deploy.load_problems()}


def now(project: str, *, who: str, yes: bool = False) -> dict:
    """Deploy the project's main code right now (needs yes); returns the result."""
    common.project_dir(project)
    if not yes:
        raise common.OpsError("This deploys the project's live site now. Run it again with --yes.")
    common.record_command(who, f"deploy now {project}", project=project)
    result = deploy.run_deploy(common.make_adapters(), project, who=who)
    result.setdefault("message", _words(result))
    return result


def _words(result: dict) -> str:
    """One plain line about a deploy result."""
    if result.get("skipped"):
        return f"Nothing to deploy ({result['skipped']})."
    if result.get("ok"):
        return f"Deployed to {result.get('url') or 'the server'}."
    if result.get("rolled_back"):
        return f"Deploy failed and was rolled back: {result.get('reason', '')}"
    return f"Deploy failed: {result.get('reason', '')}"


def _deployer_facts(project: str) -> dict:
    """{name, title, supported} of the project's deployer ('none' when unset or unreadable)."""
    from phoenix9 import settings
    try:
        name = settings.load_project(paths.projects() / project).get("deploy", {}).get(
            "with", settings.PROJECT_SCHEMA["deploy.with"].default)
    except settings.SettingsError:
        name = "none"
    found = deploy.get(name) if name != deploy.NONE else None
    if found is None:
        return {"name": name, "title": name if name != deploy.NONE else "None", "supported": name == deploy.NONE}
    return {"name": name, "title": found["title"], "supported": bool(found["supported"])}


def status(project: str) -> dict:
    """The deployer, the last few deploys, the live address and the last good commit."""
    common.project_dir(project)
    records = [r for r in deploy.read_records(project) if r.get("kind") == "deploy"]
    good = deploy.last_good(project)
    return {"project": project, "deployer": _deployer_facts(project), "recent": records[-RECENT:][::-1], "live_url": (good or {}).get("url", ""),
            "last_good_commit": (good or {}).get("commit", ""), "last_good_at": (good or {}).get("at", "")}
