"""Loads the plug-in libraries from folders (docs/architecture.md section 4).

Each plug-in kind (steps now; deployers, services, profiles later) is a folder of small folders, one
per plug-in, each holding one TOML file. `load_folders` reads any such kind; a broken folder becomes a
plain-English problem and is left out. Nothing here ever raises on bad library content, and no code
(run.py) is imported here.
"""
from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# The three groups a run walks through, in order.
GROUPS = ("run-start", "task", "run-finish")
GROUP_TITLES = {"run-start": "Run start", "task": "Each task", "run-finish": "Run finish"}

KINDS = ("script", "ai", "gate")
LEVELS = ("run", "task")
PHASES = ("start", "finish")
DEFAULTS = ("always", "on", "off")
PROVIDED_SCOPES = ("run", "task")
PROXY_PROJECT = "@project"      # in a step's proxy list: every connected store-and-wire service of the project


# ---------------------------------------------------------------------------------------------
# Small schema checker, shared by every plug-in kind.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    """One allowed key in a plug-in's TOML file: its type, whether it must be there, allowed values."""
    name: str
    type: type | tuple[type, ...]
    required: bool = False
    default: Any = None
    choices: tuple = ()
    list_of: type | None = None  # for lists: the type every item must have


def _type_name(t: type | tuple[type, ...]) -> str:
    """A plain word for a Python type, for problem messages."""
    names = {str: "text", int: "a whole number", bool: "true/false", list: "a list", dict: "a table"}
    if isinstance(t, tuple):
        if set(t) == {int, float}:
            return "a number"
        return " or ".join(names.get(x, x.__name__) for x in t)
    return names.get(t, t.__name__)


def _is_type(value: Any, t: type | tuple[type, ...]) -> bool:
    """isinstance, except that true/false never counts as a number."""
    if isinstance(value, bool):
        wanted = t if isinstance(t, tuple) else (t,)
        return bool in wanted
    return isinstance(value, t)


def check_fields(data: dict, fields: list[Field], where: str) -> tuple[dict, list[str]]:
    """Check a TOML table against its fields; return the values with defaults filled in, and all problems."""
    problems: list[str] = []
    known = {f.name for f in fields}
    for key in data:
        if key not in known:
            problems.append(f"{where}: unknown key '{key}'")
    values: dict = {}
    for f in fields:
        if f.name not in data:
            if f.required:
                problems.append(f"{where}: missing required key '{f.name}'")
            values[f.name] = _copy_default(f.default)
            continue
        value = data[f.name]
        if not _is_type(value, f.type):
            problems.append(f"{where}: '{f.name}' must be {_type_name(f.type)}")
            continue
        if f.choices and value not in f.choices:
            allowed = ", ".join(repr(c) for c in f.choices)
            problems.append(f"{where}: '{f.name}' is {value!r}, must be one of {allowed}")
            continue
        if f.list_of is not None and not all(_is_type(v, f.list_of) for v in value):
            problems.append(f"{where}: every item in '{f.name}' must be {_type_name(f.list_of)}")
            continue
        values[f.name] = value
    return values, problems


def _copy_default(value: Any) -> Any:
    """Give each loaded item its own copy of a list/dict default."""
    if isinstance(value, (list, dict)):
        return type(value)(value)
    return value


def read_toml(path: Path, where: str) -> tuple[dict | None, str | None]:
    """Read one TOML file; return (data, None) or (None, plain-English problem)."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh), None
    except FileNotFoundError:
        return None, f"{where}: file is missing"
    except tomllib.TOMLDecodeError as err:
        return None, f"{where}: not valid TOML ({err})"
    except UnicodeDecodeError:
        return None, f"{where}: is not UTF-8 text"
    except OSError as err:
        return None, f"{where}: cannot be read ({err.strerror})"


def load_folders(kind_dir: Path, filename: str,
                 parse: Callable[[dict, Path, str], tuple[Any, list[str]]]) -> tuple[list, list[str]]:
    """Load every plug-in folder in kind_dir (skipping names starting with _ or .) with parse.

    parse(data, folder, where) returns (item or None, problems). Returns (items, problems); a folder
    with problems is left out. This is the one folder-loading pattern every plug-in kind uses.
    """
    items: list = []
    problems: list[str] = []
    if not kind_dir.is_dir():
        return items, [f"{kind_dir.name}/: folder is missing"]
    for folder in sorted(kind_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith(("_", ".")):
            continue
        where = f"{kind_dir.name}/{folder.name}/{filename}"
        data, problem = read_toml(folder / filename, where)
        if problem:
            problems.append(problem)
            continue
        item, item_problems = parse(data, folder, where)
        if item_problems or item is None:
            problems.extend(item_problems)
            continue
        items.append(item)
    return items, problems


# ---------------------------------------------------------------------------------------------
# Things (steps/_things.toml)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Thing:
    """A named thing steps can need or produce: always provided by Phoenix, or with a fallback."""
    name: str
    provided: str = ""      # "" | "run" (available everywhere) | "task" (task-level steps only)
    fallback: str = ""      # "" = no fallback: an enabled earlier step must produce it
    description: str = ""

    def provided_for(self, group: str) -> bool:
        """True when Phoenix itself supplies this thing to a step in the given group."""
        if self.provided == "run":
            return True
        return self.provided == "task" and group == "task"


THING_FIELDS = [
    Field("provided", str, choices=PROVIDED_SCOPES, default=""),
    Field("fallback", str, default=""),
    Field("description", str, default=""),
]


def load_things(path: Path) -> tuple[dict[str, Thing], list[str]]:
    """Read steps/_things.toml into {name: Thing}; return the things and every problem found."""
    where = f"steps/{path.name}"
    data, problem = read_toml(path, where)
    if problem:
        return {}, [problem]
    things: dict[str, Thing] = {}
    problems: list[str] = []
    for name, table in data.items():
        spot = f"{where} [{name}]"
        if not isinstance(table, dict):
            problems.append(f"{spot}: must be a table")
            continue
        values, bad = check_fields(table, THING_FIELDS, spot)
        if not bad and "provided" in table and "fallback" in table:
            bad.append(f"{spot}: has both 'provided' and 'fallback'; use one")
        if not bad and "provided" not in table and "fallback" not in table:
            bad.append(f"{spot}: needs 'provided' or 'fallback' (fallback = \"\" means none)")
        if bad:
            problems.extend(bad)
            continue
        things[name] = Thing(name=name, **values)
    return things, problems


# ---------------------------------------------------------------------------------------------
# Steps (steps/<name>/step.toml)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One step from the library, exactly as its step.toml says (defaults filled in)."""
    name: str
    title: str
    kind: str
    level: str
    order: int
    description: str = ""
    phase: str = ""
    needs: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    safety: bool = False
    default: str = "on"
    only_with: tuple[str, ...] = ()
    proxy: tuple[str, ...] = ()
    settings: dict = field(default_factory=dict, compare=False)
    ai: dict = field(default_factory=dict, compare=False)
    folder: Path | None = field(default=None, compare=False)

    @property
    def group(self) -> str:
        """Which part of the run this step belongs to: run-start, task or run-finish."""
        return group_of(self.level, self.phase)

    @property
    def sort_key(self) -> tuple[int, int]:
        """Run order: group first (run-start, task, run-finish), then order inside the group."""
        return GROUPS.index(self.group), self.order

    @property
    def can_switch_off(self) -> bool:
        """False for default = "always" steps."""
        return self.default != "always"


def group_of(level: str, phase: str) -> str:
    """The group name for a (level, phase) pair."""
    if level == "task":
        return "task"
    return "run-start" if phase == "start" else "run-finish"


STEP_FIELDS = [
    Field("name", str, required=True),
    Field("title", str, required=True),
    Field("description", str, default=""),
    Field("kind", str, required=True, choices=KINDS),
    Field("level", str, required=True, choices=LEVELS),
    Field("phase", str, default="", choices=("",) + PHASES),
    Field("order", int, required=True),
    Field("needs", list, default=[], list_of=str),
    Field("produces", list, default=[], list_of=str),
    Field("safety", bool, default=False),
    Field("default", str, default="on", choices=DEFAULTS),
    Field("only_with", list, default=[], list_of=str),
    Field("proxy", list, default=[], list_of=str),
    Field("settings", dict, default={}),
    Field("ai", dict, default={}),
]


def parse_step(data: dict, folder: Path, where: str) -> tuple[Step | None, list[str]]:
    """Check one step.toml on its own (no cross-step checks) and turn it into a Step."""
    values, problems = check_fields(data, STEP_FIELDS, where)
    if problems:
        return None, problems
    if values["name"] != folder.name:
        problems.append(f"{where}: name is '{values['name']}' but the folder is '{folder.name}'")
    if values["level"] == "run" and not values["phase"]:
        problems.append(f"{where}: run-level steps need phase = \"start\" or \"finish\"")
    if values["level"] == "task" and values["phase"]:
        problems.append(f"{where}: 'phase' is only for run-level steps; task steps use 'order' only")
    if values["ai"] and values["kind"] != "ai":
        problems.append(f"{where}: an [ai] block is only for kind = \"ai\" steps")
    if values["name"] in values["only_with"]:
        problems.append(f"{where}: only_with cannot name the step itself")
    if values["default"] == "always" and values["only_with"]:
        problems.append(f"{where}: an always-on step cannot depend on other steps with only_with")
    if problems:
        return None, problems
    for key in ("needs", "produces", "only_with", "proxy"):
        values[key] = tuple(values[key])
    return Step(folder=folder, **values), []


def _cross_check(steps: list[Step], things: dict[str, Thing], root: Path | None = None) -> tuple[list[Step], list[str]]:
    """Checks that need the whole library: known things, no order ties, only_with names exist, proxy names."""
    problems: list[str] = []
    bad: set[str] = set()
    if root is not None and any(s.proxy for s in steps):
        from phoenix9 import services     # late import: services.py imports this module
        known = services.names_in(root)
        for s in steps:
            for name in s.proxy:
                if name != PROXY_PROJECT and name not in known:
                    problems.append(f"steps/{s.name}/step.toml: proxy '{name}' is not a service "
                                    f"(use a service name or \"{PROXY_PROJECT}\")")
                    bad.add(s.name)
    for s in steps:
        for key in ("needs", "produces"):
            for thing in getattr(s, key):
                if thing not in things:
                    problems.append(f"steps/{s.name}/step.toml: {key} '{thing}', which is not in "
                                    f"steps/_things.toml")
                    bad.add(s.name)
    by_slot: dict[tuple, list[str]] = {}
    for s in steps:
        by_slot.setdefault((s.level, s.phase, s.order), []).append(s.name)
    for (level, phase, order), names in by_slot.items():
        if len(names) > 1:
            spot = f"{level}-level" + (f" ({phase})" if phase else "")
            problems.append(f"steps {', '.join(names)}: share order {order} in the {spot} steps; "
                            f"each needs its own order number")
            bad.update(names)
    # only_with must name steps that are loaded; removing one step can break another, so repeat.
    while True:
        kept = {s.name for s in steps if s.name not in bad}
        newly = set()
        for s in steps:
            if s.name in bad:
                continue
            for other in s.only_with:
                if other not in kept:
                    problems.append(f"steps/{s.name}/step.toml: only_with names '{other}', "
                                    f"which is not a working step")
                    newly.add(s.name)
        if not newly:
            break
        bad |= newly
    return [s for s in steps if s.name not in bad], problems


# ---------------------------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------------------------

@dataclass
class Library:
    """Everything loaded from a library root: steps in run order, things, and plain-English problems."""
    root: Path
    steps: list[Step] = field(default_factory=list)
    things: dict[str, Thing] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def step(self, name: str) -> Step:
        """The step with this name; KeyError (plain English) when there is none."""
        for s in self.steps:
            if s.name == name:
                return s
        raise KeyError(f"there is no step called '{name}' in the library")

    def has_step(self, name: str) -> bool:
        """True when a working step with this name was loaded."""
        return any(s.name == name for s in self.steps)

    def steps_in(self, level: str, phase: str = "") -> list[Step]:
        """Steps of one level (and, for run level, one phase), in order."""
        return [s for s in self.steps if s.level == level and (level == "task" or s.phase == phase)]

    def group(self, group: str) -> list[Step]:
        """Steps of one group ("run-start", "task", "run-finish"), in order."""
        return [s for s in self.steps if s.group == group]


def load_library(root: Path) -> Library:
    """Load steps/<name>/step.toml for every folder plus steps/_things.toml; never raises."""
    root = Path(root)
    things, problems = load_things(root / "steps" / "_things.toml")
    steps, step_problems = load_folders(root / "steps", "step.toml", parse_step)
    problems += step_problems
    steps, cross_problems = _cross_check(steps, things, root)
    problems += cross_problems
    steps.sort(key=lambda s: s.sort_key)
    return Library(root=root, steps=steps, things=things, problems=problems)


class CodeError(Exception):
    """A step's run.py could not be imported; the message is the plain-English reason."""


def load_code(lib: Library, step: Step | str):
    """Import steps/<name>/run.py and return the module, or None when the step has no run.py.

    A run.py that fails to import raises CodeError (the runner turns that into a failed step).
    """
    if isinstance(step, str):
        step = lib.step(step)
    folder = step.folder or lib.root / "steps" / step.name
    path = Path(folder) / "run.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"phoenix_step_{step.name.replace('-', '_')}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException as err:  # a broken step must never crash the runner
        if isinstance(err, KeyboardInterrupt):
            raise
        raise CodeError(f"steps/{step.name}/run.py could not be loaded: {type(err).__name__}: {err}") from err
    return module
