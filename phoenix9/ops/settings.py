"""Ops for a project's settings: show, set, preset, explain and check."""
from phoenix9 import events, resolve, settings as core
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


def _fail(err: Exception):
    raise OpsError(str(err)) from None


def show(project: str) -> dict:
    """The effective settings with where each value came from."""
    folder = common.project_dir(project)
    try:
        eff = core.effective(folder, common.library())
    except core.SettingsError as err:
        _fail(err)
    return {"project": project, "values": eff.values, "source": eff.source}


def set(project: str, key: str, value: str, who: str = "cli") -> dict:
    """Set one key (like steps.builder.model) in the project's phoenix.toml."""
    folder = common.project_dir(project)
    try:
        core.set_value(folder, key, value, common.library())
    except core.SettingsError as err:
        _fail(err)
    events.emit("settings.changed", project=project, who=who, key=key)
    common.record_command(who, f"settings set {project} {key}", project, f"set {key} to {value}")
    return {"project": project, "key": key, "value": value}


def preset(project: str, name: str, who: str = "cli") -> dict:
    """Choose a preset for the project."""
    folder = common.project_dir(project)
    try:
        core.apply_preset(folder, name, common.library())
    except core.SettingsError as err:
        _fail(err)
    events.emit("settings.changed", project=project, who=who, key="preset")
    common.record_command(who, f"settings preset {project} {name}", project, f"chose the {name} preset")
    return {"project": project, "preset": name}


def explain(project: str) -> dict:
    """The plain-English plan for the project's settings."""
    folder = common.project_dir(project)
    try:
        return {"project": project, "text": core.explain(folder, common.library())}
    except (core.SettingsError, resolve.ResolveError) as err:
        _fail(err)


def check(project: str) -> dict:
    """Every problem found in the project's settings (an empty list means fine)."""
    folder = common.project_dir(project)
    problems = core.check(folder, common.library())
    return {"project": project, "ok": not problems, "problems": problems}
