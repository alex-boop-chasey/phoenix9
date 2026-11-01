"""Project settings: read and check phoenix.toml, layer it over presets and profiles, and explain it.

Layers, lowest first (docs/architecture.md 5.1): library defaults, profile, preset, project, run.
Every value remembers which layer set it. Unknown keys are errors everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from . import paths, tomlw
from .library import Library, _is_type, _type_name, load_library, read_toml
from .resolve import resolve

LAYERS = ("library", "profile", "preset", "project", "run")
PRESETS = ("simple", "quick", "full", "custom")
CLAUDE_MD = ("library", "project", "both")
ADVISOR_WHEN = ("blocked", "before-done", "on-demand")
PRESET_META = ("title", "description")  # allowed in a preset file, ignored by settings

HEADER = "Phoenix 9 project settings. Change them with `phoenix settings`, or edit by hand."
KEY_ORDER = ["preset", "based_on", "profile", "merge", "max_tries", "on_failure", "services",
             "safety_files", "home_chat_may_answer", "diff", "domains", "steps", "deploy",
             "allow_extra", "deny_extra", "allow", "on", "model", "with", "mode", "preview"]


class SettingsError(Exception):
    """A settings problem in plain English, naming the file, the key and what is wrong."""


@dataclass(frozen=True)
class Spec:
    """One settable key: its type, library default, and allowed values (for lists: allowed items)."""
    type: type
    default: Any
    item_type: type | None = None
    choices: tuple = ()


def _spec(default: Any, choices: tuple = (), item_type: type | None = None) -> Spec:
    """A Spec whose type comes from its default value."""
    return Spec(type(default), default, item_type, choices)


# Top-level keys of phoenix.toml (architecture 5.2) with their library defaults.
PROJECT_SCHEMA: dict[str, Spec] = {
    "preset": _spec("quick", PRESETS),
    "based_on": _spec("quick", tuple(p for p in PRESETS if p != "custom")),
    "profile": _spec(""),
    "merge": _spec("auto", ("auto", "ask")),
    "max_tries": _spec(3),
    "on_failure": _spec("pause", ("continue", "pause", "delegate")),
    "services": _spec([], item_type=str),
    "safety_files": _spec([], item_type=str),
    "home_chat_may_answer": _spec([], item_type=str),
    "diff.allow_extra": _spec([], item_type=str),
    "diff.deny_extra": _spec([], item_type=str),
    "domains.allow": _spec([], item_type=str),
    "deploy.with": _spec("none"),
    "deploy.mode": _spec("off", ("on-merge", "button", "off")),
    "deploy.preview": _spec(False),
}

# The ai block keys any ai step may set (architecture 5.3); a step's own [ai] gives its defaults.
AI_SCHEMA: dict[str, Spec] = {
    "model": _spec(""),
    "fallback_models": _spec([], item_type=str),
    "tools": _spec([], item_type=str),
    "tools_denied": _spec([], item_type=str),
    "mcp_servers": _spec([], item_type=str),
    "claude_md": _spec("library", CLAUDE_MD),
    "skills": _spec([], item_type=str),
    "max_turns": _spec(40),
    "timeout": _spec(30),
    "advisor.on": _spec(False),
    "advisor.model": _spec(""),
    "advisor.when": _spec([], ADVISOR_WHEN, str),
    "advisor.instructions": _spec(""),
}


def step_specs(lib: Library) -> dict[str, Spec]:
    """Every settable key under steps.<name>, with defaults from the library step."""
    specs: dict[str, Spec] = {}
    for step in lib.steps:
        base = f"steps.{step.name}"
        specs[f"{base}.on"] = _spec(step.default != "off")
        for key, value in step.settings.items():
            item = type(value[0]) if isinstance(value, list) and value else None
            specs[f"{base}.{key}"] = Spec(type(value), value, item or (str if isinstance(value, list) else None))
        if step.kind == "ai":
            for key, spec in AI_SCHEMA.items():
                default = _nested(step.ai, key.split("."), spec.default)
                specs[f"{base}.{key}"] = Spec(spec.type, default, spec.item_type, spec.choices)
    return specs


def all_specs(lib: Library) -> dict[str, Spec]:
    """Every settable dotted key in a project's phoenix.toml."""
    return {**PROJECT_SCHEMA, **step_specs(lib)}


def _nested(data: dict, parts: list[str], default: Any) -> Any:
    """Look up a path of keys in nested dicts; default when any part is missing."""
    for part in parts:
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    """Nested dict to {dotted.path: value}; lists and empty tables are values."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(_flatten(value, path + "."))
        else:
            flat[path] = value
    return flat


def _unflatten(flat: dict[str, Any]) -> dict:
    """{dotted.path: value} back to a nested dict."""
    out: dict = {}
    for path, value in flat.items():
        node = out
        *parents, last = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    return out


def _leaf_problems(path: str, value: Any, spec: Spec, where: str) -> list[str]:
    """Problems with one value against its spec (type, list items, allowed values)."""
    if not _is_type(value, spec.type):
        return [f"{where}: '{path}' must be {_type_name(spec.type)}"]
    items = value if spec.type is list else [value]
    if spec.type is list and spec.item_type and not all(_is_type(v, spec.item_type) for v in items):
        return [f"{where}: every item in '{path}' must be {_type_name(spec.item_type)}"]
    if spec.choices:
        bad = [v for v in items if v not in spec.choices]
        if bad:
            allowed = ", ".join(repr(c) for c in spec.choices)
            return [f"{where}: '{path}' is {bad[0]!r}, must be one of {allowed}"]
    return []


def validate(data: dict, specs: dict[str, Spec], where: str) -> list[str]:
    """All problems in one settings table: unknown keys, wrong types, values not allowed."""
    problems: list[str] = []
    prefixes = {p.rsplit(".", i)[0] for p in specs for i in range(1, p.count(".") + 1)}
    for path, value in _flatten(data).items():
        if path in specs:
            problems += _leaf_problems(path, value, specs[path], where)
        elif path in prefixes:
            problems.append(f"{where}: '{path}' must be a table")
        else:
            problems.append(f"{where}: unknown key '{path}'")
    return problems


# ---------------------------------------------------------------------------------------------
# Reading and writing phoenix.toml
# ---------------------------------------------------------------------------------------------

def project_file(project_dir) -> Path:
    """Where a project's phoenix.toml lives."""
    return Path(project_dir) / "phoenix.toml"


def load_project(project_dir) -> dict:
    """Read phoenix.toml as a dict; a missing file is {}; broken TOML raises SettingsError."""
    path = project_file(project_dir)
    if not path.exists():
        return {}
    data, problem = read_toml(path, "phoenix.toml")
    if problem:
        raise SettingsError(problem)
    return data


def _lib_or_default(lib: Library | None) -> Library:
    """The given library, or the running copy's library."""
    return lib if lib is not None else load_library(paths.library())


UPDATE_DEFAULTS = {"project": "phoenix9", "repo": "alex-boop-chasey/phoenix9", "tag_prefix": "v9."}


def read_global() -> dict:
    """HOME/config/global.toml as a dict ({} when missing or broken)."""
    try:
        return tomllib.loads((paths.config() / "global.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update_settings() -> dict:
    """The [update] table of global.toml (project, repo, tag_prefix) with defaults filled in."""
    table = read_global().get("update")
    table = table if isinstance(table, dict) else {}
    return {k: (table[k] if isinstance(table.get(k), str) and table[k] else d) for k, d in UPDATE_DEFAULTS.items()}


def self_project_problems(name: str, data: dict) -> list[str]:
    """Extra rules for the project that is Phoenix 9 itself: merge fixed to ask, no deployer."""
    if name != update_settings()["project"]:
        return []
    problems = []
    if data.get("merge", PROJECT_SCHEMA["merge"].default) != "ask":
        problems.append("phoenix.toml: phoenix9's merge mode is fixed to ask (updates spec 3.2)")
    if data.get("deploy", {}).get("with", PROJECT_SCHEMA["deploy.with"].default) != "none":
        problems.append("phoenix.toml: phoenix9 installs itself through the updater, so [deploy] with must be none")
    return problems


def check(project_dir, lib: Library | None = None) -> list[str]:
    """Every problem in the project's phoenix.toml (not just the first); empty when it is fine."""
    try:
        data = load_project(project_dir)
    except SettingsError as err:
        return [str(err)]
    return (validate(data, all_specs(_lib_or_default(lib)), "phoenix.toml")
            + self_project_problems(Path(project_dir).name, data))


def _prune(data: dict) -> dict:
    """Drop empty tables so saved files stay tidy."""
    out = {}
    for key, value in data.items():
        if isinstance(value, dict):
            value = _prune(value)
            if not value:
                continue
        out[key] = value
    return out


def save_project(project_dir, data: dict) -> None:
    """Write phoenix.toml with keys in the architecture 5.2 order."""
    tomlw.dump(project_file(project_dir), _prune(data), header=HEADER, key_order=KEY_ORDER)


# ---------------------------------------------------------------------------------------------
# Presets and profiles
# ---------------------------------------------------------------------------------------------

def _read_layer(path: Path, what: str) -> dict:
    """Read a preset or profile file; SettingsError when missing or broken."""
    if not path.is_file():
        raise SettingsError(f"{what}: file is missing ({path})")
    data, problem = read_toml(path, what)
    if problem:
        raise SettingsError(problem)
    return data


def _plain_name(name: str, what: str) -> None:
    """Refuse names that could point outside the library folder."""
    if not name or "/" in name or name.startswith("."):
        raise SettingsError(f"{what} name '{name}' is not allowed")


def load_preset(lib_root, name: str) -> dict:
    """Read presets/<name>.toml; `custom` has no file and gives {}."""
    if name == "custom":
        return {}
    _plain_name(name, "preset")
    data = _read_layer(Path(lib_root) / "presets" / f"{name}.toml", f"presets/{name}.toml")
    return {k: v for k, v in data.items() if k not in PRESET_META}


def load_profile(lib_root, name: str) -> dict:
    """Read profiles/<name>/profile.toml as a dict."""
    _plain_name(name, "profile")
    return _read_layer(Path(lib_root) / "profiles" / name / "profile.toml", f"profiles/{name}/profile.toml")


PROFILE_REPORTS = ("pytest-junit", "vitest-json", "playwright-json", "exit-code")

# Keys of a profile.toml outside [steps.*] (architecture 4.5).
PROFILE_SCHEMA: dict[str, Spec] = {
    "title": _spec(""),
    "image": _spec(""),
    "allowed_domains": _spec([], item_type=str),
    "diff_allow_extra": _spec([], item_type=str),
    "screenshots": _spec(False),
    "suggested_deployer": _spec("none"),
    "test.cmd": _spec(""),
    "test.task_cmd": _spec(""),
    "test.report": _spec("exit-code", PROFILE_REPORTS),
    "test.report_path": _spec(""),
    "test.checks_dir": _spec(""),
    "test.check_files": _spec(""),
    "test.check_command": _spec(""),
    "test.report_args": _spec(""),
}


def _without_report_list(own: dict) -> dict:
    """The profile's own keys, minus test.report when it is a list (checked on its own)."""
    test = own.get("test")
    if isinstance(test, dict) and isinstance(test.get("report"), list):
        return {**own, "test": {k: v for k, v in test.items() if k != "report"}}
    return own


def _report_list_problems(own: dict, where: str) -> list[str]:
    """Problems with a list-form test.report: it needs names from PROFILE_REPORTS."""
    test = own.get("test")
    report = test.get("report") if isinstance(test, dict) else None
    if not isinstance(report, list):
        return []
    bad = [r for r in report if r not in PROFILE_REPORTS]
    if not report:
        return [f"{where}: 'test.report' must not be an empty list"]
    return [f"{where}: 'test.report' has unknown report '{r}' (use {', '.join(PROFILE_REPORTS)})" for r in bad]


def check_profile(lib_root, name: str, lib: Library | None = None) -> list[str]:
    """Every problem in profiles/<name>/profile.toml (its own keys and its [steps.*] overrides)."""
    where = f"profiles/{name}/profile.toml"
    try:
        data = load_profile(lib_root, name)
    except SettingsError as err:
        return [str(err)]
    lib = lib if lib is not None else load_library(lib_root)
    own = {k: v for k, v in data.items() if k != "steps"}
    problems = validate(_without_report_list(own), PROFILE_SCHEMA, where)
    problems += _report_list_problems(own, where)
    if data.get("steps"):
        problems += validate({"steps": data["steps"]}, step_specs(lib), where)
    if not own.get("image"):
        problems.append(f"{where}: missing 'image'")
    if not own.get("test", {}).get("cmd"):
        problems.append(f"{where}: missing 'test.cmd'")
    return problems


def preset_name(project: dict) -> str:
    """The preset file that applies: the project's preset, or its based_on when preset is custom."""
    preset = project.get("preset", PROJECT_SCHEMA["preset"].default)
    if preset == "custom":
        return project.get("based_on", PROJECT_SCHEMA["based_on"].default)
    return preset


# ---------------------------------------------------------------------------------------------
# Effective settings
# ---------------------------------------------------------------------------------------------

@dataclass
class Effective:
    """The merged settings (nested like phoenix.toml, every key filled) and which layer set each one."""
    values: dict
    source: dict[str, str] = field(default_factory=dict)

    def get(self, path: str) -> Any:
        """The value at a dotted path."""
        return _nested(self.values, path.split("."), None)


def _layer(data: dict, specs: dict[str, Spec], where: str) -> dict[str, Any]:
    """Check one layer and return its flat values; SettingsError listing every problem."""
    problems = validate(data, specs, where)
    if problems:
        raise SettingsError("; ".join(problems))
    return _flatten(data)


def effective(project_dir, lib: Library, run_overrides: dict | None = None) -> Effective:
    """Merge library defaults, profile, preset, project and run overrides, remembering each source."""
    specs = all_specs(lib)
    project = load_project(project_dir)
    flat: dict[str, Any] = {}
    source: dict[str, str] = {}
    for path, spec in specs.items():
        flat[path] = list(spec.default) if isinstance(spec.default, list) else spec.default
        source[path] = "library"

    def apply(label: str, data: dict, where: str, only: str = "") -> None:
        """Overlay one layer's values; `only` limits it to keys under one prefix."""
        for path, value in _layer(data, specs, where).items():
            if path.startswith(only):
                flat[path] = value
                source[path] = label

    profile = project.get("profile", "")
    if profile:
        data = load_profile(lib.root, profile)
        if data.get("steps"):               # a profile with no [steps.*] changes nothing
            apply(f"profile:{profile}", {"steps": data["steps"]}, f"profiles/{profile}/profile.toml")
    preset = preset_name({**project, **{k: v for k, v in (run_overrides or {}).items() if k in ("preset", "based_on")}})
    apply(f"preset:{preset}", load_preset(lib.root, preset), f"presets/{preset}.toml")
    apply("project", project, "phoenix.toml")
    if run_overrides:
        apply("run", run_overrides, "run settings")
    return Effective(values=_unflatten(flat), source=source)


def enabled_map(eff: Effective) -> dict[str, bool]:
    """{step name: on?} for the resolver."""
    return {name: bool(table["on"]) for name, table in eff.values.get("steps", {}).items()}


def explain(project_dir, lib: Library) -> str:
    """The resolver's plain-English plan plus one line per non-default setting and where it came from."""
    eff = effective(project_dir, lib)
    text = resolve(lib, enabled_map(eff)).explain()
    lines = ["Settings that differ from the library defaults:"]
    changed = [(p, s) for p, s in eff.source.items() if s != "library"]
    for path, src in sorted(changed):
        lines.append(f"  {path} = {eff.get(path)!r}  (from {src})")
    if not changed:
        lines.append("  (none)")
    return text + "\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# Changing settings
# ---------------------------------------------------------------------------------------------

def _coerce(path: str, raw: str, spec: Spec) -> Any:
    """Turn typed-in text into the type the key needs."""
    if spec.type is bool:
        word = raw.strip().lower()
        if word in ("true", "yes", "on", "1"):
            return True
        if word in ("false", "no", "off", "0"):
            return False
        raise SettingsError(f"'{path}' must be true or false, not '{raw}'")
    if spec.type is int:
        try:
            return int(raw.strip())
        except ValueError:
            raise SettingsError(f"'{path}' must be a whole number, not '{raw}'") from None
    if spec.type is list:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if spec.item_type is int:
            try:
                return [int(p) for p in parts]
            except ValueError:
                raise SettingsError(f"every item in '{path}' must be a whole number") from None
        return parts
    return raw


def set_value(project_dir, dotted_key: str, raw_value: str, lib: Library | None = None) -> None:
    """Set one key from typed-in text (steps.builder.model=...), check it, and save phoenix.toml."""
    specs = all_specs(_lib_or_default(lib))
    if dotted_key not in specs:
        raise SettingsError(f"phoenix.toml: unknown key '{dotted_key}'")
    value = _coerce(dotted_key, raw_value, specs[dotted_key])
    problems = _leaf_problems(dotted_key, value, specs[dotted_key], "phoenix.toml")
    if problems:
        raise SettingsError(problems[0])
    data = load_project(project_dir)
    node = data
    *parents, last = dotted_key.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value
    save_project(project_dir, data)


def flat_problems(flat: dict, lib: Library | None = None) -> list[str]:
    """Every problem with typed values keyed by dotted path (unknown keys, wrong types, values not allowed)."""
    specs = all_specs(_lib_or_default(lib))
    problems = []
    for key, value in flat.items():
        if key not in specs:
            problems.append(f"phoenix.toml: unknown key '{key}'")
        else:
            problems += _leaf_problems(key, value, specs[key], "phoenix.toml")
    return problems


def set_values(project_dir, flat: dict, lib: Library | None = None) -> None:
    """Set many typed values keyed by dotted path; every problem is reported and nothing is written unless all pass."""
    problems = flat_problems(flat, lib)
    if problems:
        raise SettingsError("; ".join(problems))
    data = load_project(project_dir)
    for key, value in flat.items():
        node = data
        *parents, last = key.split(".")
        for part in parents:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[last] = value
    save_project(project_dir, data)


def apply_preset(project_dir, name: str, lib: Library | None = None) -> None:
    """Choose a preset: set `preset` and drop every per-step `on`; other step settings stay."""
    if name not in PRESETS:
        raise SettingsError(f"phoenix.toml: preset '{name}' must be one of "
                            + ", ".join(repr(p) for p in PRESETS))
    if lib is not None:
        load_preset(lib.root, name)  # raises when the preset file is missing
    data = load_project(project_dir)
    data["preset"] = name
    for table in data.get("steps", {}).values():
        if isinstance(table, dict):
            table.pop("on", None)
    save_project(project_dir, data)
