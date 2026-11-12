"""Ops for a project's settings: show, set, preset, explain and check.

A chat caller (who = chat:*, the Phoenix agent or a project chat) may not change a safety setting here
(`is_safety_key`: the spending cap, what happens when a task fails, sites, diff rules, safety files,
services, tools, MCP, safety steps...). Alex changes those himself in Settings (the dashboard) or the CLI."""
import shutil
import tempfile
from pathlib import Path

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


def _is_chat(who) -> bool:
    return str(who or "").startswith("chat:") or who == "agent"


def _refuse_chat_safety(who, keys, lib=None) -> None:
    """Raise OpsError when a chat caller tries to change any safety key."""
    if not _is_chat(who):
        return
    lib = lib or common.library()
    hit = sorted(k for k in keys if is_safety_key(k, lib))
    if hit:
        raise OpsError(f"'{who}' may not change {', '.join(hit)}. {SAFETY_REASON}")


def set(project: str, key: str, value: str, who: str = "cli") -> dict:
    """Set one key (like steps.builder.model) in the project's phoenix.toml."""
    folder = common.project_dir(project)
    _refuse_chat_safety(who, [key])
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
    _refuse_chat_safety(who, [key])
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
    _refuse_chat_safety(who, list(values or {}))
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
    _refuse_chat_safety(who, list(flat))
    if name is not None and _is_chat(who):
        _refuse_chat_preset(folder, name, who)
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
    if _is_chat(who):
        _refuse_chat_preset(folder, name, who)
    try:
        core.apply_preset(folder, name, common.library())
    except core.SettingsError as err:
        _fail(err)
    events.emit("settings.changed", project=project, who=who, key="preset")
    common.record_command(who, f"settings preset {project} {name}", project, f"chose the {name} preset")
    return {"project": project, "preset": name}


def _refuse_chat_preset(folder, name: str, who: str) -> None:
    """A chat may choose a preset only when it changes no safety setting (e.g. Simple turns Verify off)."""
    lib = common.library()
    with tempfile.TemporaryDirectory(prefix="phoenix-preset-") as tmp:
        src = core.project_file(folder)
        if Path(src).exists():
            shutil.copy(src, core.project_file(tmp))
        try:
            before = core.effective(tmp, lib).values
            core.apply_preset(tmp, name, lib)
            after = core.effective(tmp, lib).values
        except core.SettingsError as err:
            _fail(err)
    flat_before, flat_after = core._flatten(before), core._flatten(after)
    changed = [k for k in sorted({*flat_before, *flat_after})
               if flat_before.get(k) != flat_after.get(k) and is_safety_key(k, lib)]
    if changed:
        raise OpsError(f"'{who}' may not choose the {name} preset: it changes {', '.join(changed)}. {SAFETY_REASON}")


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


SAFETY_TOP = ("budget_usd", "on_failure", "domains", "diff", "safety_files", "services", "home_chat_may_answer",
              "profile")
SAFETY_WORDS = ("tool", "mcp")
SAFETY_KEYS = ("steps.planner.auto_approve",)      # answers the plan question without a person
SAFETY_REASON = "This is a safety setting: change this in Settings yourself."


def is_safety_key(key: str, lib=None) -> bool:
    """True when a dotted key loosens or tightens the agent's leash (sites, diff rules, secrets, tools, MCP, safety steps)."""
    parts = key.split(".")
    if key in SAFETY_KEYS or parts[0] in SAFETY_TOP or any(w in key.lower() for w in SAFETY_WORDS):
        return True
    if parts[0] == "steps" and len(parts) > 1:
        lib = lib or common.library()
        step = next((s for s in lib.steps if s.name == parts[1]), None)
        return step is None or bool(getattr(step, "safety", False))
    return False


def dry_check(project: str, values: dict, agent: bool = False) -> list[dict]:
    """Check a proposed change key by key as set_many would, writing nothing: [{key, ok, reason}].

    With agent=True (a change the agent proposed) every safety key is refused: only Alex changes those in Settings."""
    common.project_dir(project)
    lib = common.library()
    rows = []
    for key, value in values.items():
        problems = core.flat_problems({key: value}, lib)
        reason = "; ".join(p.removeprefix("phoenix.toml: ") for p in problems)
        if agent and is_safety_key(key, lib):
            problems, reason = [SAFETY_REASON], SAFETY_REASON
        rows.append({"key": key, "ok": not problems, "reason": reason})
    return rows
