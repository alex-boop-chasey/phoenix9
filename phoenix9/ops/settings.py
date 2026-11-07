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


def change_list(project: str, key: str, item: str, add: bool, who: str = "cli") -> dict:
    """Add one item to (or remove it from) a list setting such as safety_files or services."""
    folder = common.project_dir(project)
    try:
        value = core.change_list(folder, key, item, add, common.library())
    except core.SettingsError as err:
        _fail(err)
    verb = "add" if add else "remove"
    events.emit("settings.changed", project=project, who=who, key=key)
    common.record_command(who, f"settings {verb} {project} {key}", project,
                          f"{'added' if add else 'removed'} {item} {'to' if add else 'from'} {key}")
    return {"project": project, "key": key, "item": item, "value": value}


def set_many(project: str, values: dict, who: str = "cli") -> dict:
    """Set several keys (typed values by dotted path) at once; nothing is written unless all are fine."""
    folder = common.project_dir(project)
    try:
        core.set_values(folder, values, common.library())
    except core.SettingsError as err:
        _fail(err)
    keys = sorted(values)
    events.emit("settings.changed", project=project, who=who, keys=keys)
    common.record_command(who, f"settings set {project} {' '.join(keys)}", project,
                          f"set {', '.join(keys)}")
    return {"project": project, "set": keys}


def save_defaults(project: str, overrides: dict, who: str = "cli") -> dict:
    """Save wizard settings as the project's defaults: the preset first, then the rest as dotted keys."""
    folder = common.project_dir(project)
    rest = dict(overrides or {})
    name = rest.pop("preset", None)
    flat = core._flatten(rest)
    try:
        lib = common.library()
        problems = core.flat_problems(flat, lib)
        if problems:
            raise core.SettingsError("; ".join(problems))
        if name is not None:
            core.apply_preset(folder, name, lib)
        if flat:
            core.set_values(folder, flat, lib)
    except core.SettingsError as err:
        _fail(err)
    events.emit("settings.changed", project=project, who=who, key="defaults")
    common.record_command(who, f"settings defaults {project}", project, "saved the build settings as defaults")
    return {"project": project}


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


def dry_check(project: str, values: dict) -> list[dict]:
    """Check a proposed change key by key as set_many would, writing nothing: [{key, ok, reason}]."""
    common.project_dir(project)
    lib = common.library()
    rows = []
    for key, value in values.items():
        problems = core.flat_problems({key: value}, lib)
        reason = "; ".join(p.removeprefix("phoenix.toml: ") for p in problems)
        rows.append({"key": key, "ok": not problems, "reason": reason})
    return rows
