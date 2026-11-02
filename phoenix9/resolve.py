"""Works out which steps actually run and where each step's inputs come from (architecture 4.3).

Rules: always-on steps cannot be switched off; a step with only_with is off when any listed step is
off; each need is met by the latest earlier enabled producer, else Phoenix provides it, else the
thing's fallback, else it is an error. Pure: reads a Library and an on/off map, touches nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from phoenix9.library import GROUP_TITLES, GROUPS, Library, Step


class ResolveError(Exception):
    """The on/off choices cannot work; `problems` lists every reason in plain English."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass
class Row:
    """One step's line in the plan: whether it runs, why not, and where each need comes from."""
    name: str
    title: str
    group: str
    order: int
    kind: str
    safety: bool
    default: str
    on: bool
    reason: str = ""                                   # why it is off ("" when on)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    """The effective step plan: groups of step names in run order, need sources, and off reasons."""
    groups: dict[str, list[str]]
    sources: dict[str, dict[str, str]]
    off: dict[str, str]
    rows: list[Row]

    def is_on(self, name: str) -> bool:
        """True when the step runs in this plan."""
        return any(name in names for names in self.groups.values())

    def to_json(self) -> dict:
        """JSON-able dict for plan.json, the API and --json output (json.dumps reads back equal)."""
        return {
            "groups": {g: list(names) for g, names in self.groups.items()},
            "sources": {s: dict(needs) for s, needs in self.sources.items()},
            "off": dict(self.off),
            "steps": [vars(r) | {"sources": dict(r.sources)} for r in self.rows],
        }

    def explain(self) -> str:
        """The plain-English plan that `phoenix settings explain` prints, one block per group."""
        lines: list[str] = []
        for group in GROUPS:
            lines.append(f"{GROUP_TITLES[group]}:")
            rows = [r for r in self.rows if r.group == group]
            if not rows:
                lines.append("  (no steps)")
            for r in rows:
                lines.append(_row_line(r))
                for need, source in r.sources.items():
                    lines.append(f"      needs {need}: {describe_source(source)}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


# Steps that are "on" but skip themselves until a project setting asks for them.
SELF_SKIP = {"preview": "skips unless [deploy] preview = true",
             "deploy": "skips unless [deploy] mode is on-merge or button"}


def _row_line(r: Row) -> str:
    """One step's headline in explain(): on/off, title, name, labels, and why when off."""
    state = "ON " if r.on else "off"
    labels = []
    if r.safety:
        labels.append("safety")
    if r.default == "always":
        labels.append("always on")
    label = f" [{', '.join(labels)}]" if labels else ""
    why = f" ({r.reason})" if not r.on else f" ({SELF_SKIP[r.name]})" if r.name in SELF_SKIP else ""
    return f"  {state}  {r.order:>3}  {r.title} ({r.name}){label}{why}"


def describe_source(source: str) -> str:
    """Plain English for a source string: step:<name>, provided, fallback:<name>."""
    if source == "provided":
        return "provided by Phoenix"
    kind, _, name = source.partition(":")
    if kind == "step":
        return f"from {name}"
    return f"fallback '{name}'"


def resolve(lib: Library, enabled: dict[str, bool]) -> Plan:
    """Compute the effective plan for an on/off map; raise ResolveError listing every problem."""
    _check_choices(lib, enabled)
    on, off = _switch(lib, enabled)
    active = [s for s in lib.steps if on[s.name]]
    sources, problems = _find_sources(lib, active, off)
    if problems:
        raise ResolveError(problems)
    rows = [Row(name=s.name, title=s.title, group=s.group, order=s.order, kind=s.kind,
                safety=s.safety, default=s.default, on=on[s.name], reason=off.get(s.name, ""),
                sources=sources.get(s.name, {}))
            for s in lib.steps]
    groups = {g: [s.name for s in active if s.group == g] for g in GROUPS}
    return Plan(groups=groups, sources=sources, off=off, rows=rows)


def _check_choices(lib: Library, enabled: dict[str, bool]) -> None:
    """Rules 1 and 4: unknown step names and switching off an always-on step are errors."""
    problems = []
    for name, value in enabled.items():
        if not lib.has_step(name):
            problems.append(f"There is no step called '{name}' in the library.")
        elif not value and lib.step(name).default == "always":
            problems.append(f"{lib.step(name).title} can't be switched off; it always runs.")
    if problems:
        raise ResolveError(problems)


def _switch(lib: Library, enabled: dict[str, bool]) -> tuple[dict[str, bool], dict[str, str]]:
    """Rules 1 and 2: decide on/off per step, then force off only_with steps whose partners are off."""
    on: dict[str, bool] = {}
    off: dict[str, str] = {}
    for s in lib.steps:
        if s.default == "always":
            on[s.name] = True
        elif s.name in enabled:
            on[s.name] = bool(enabled[s.name])
            if not on[s.name]:
                off[s.name] = "switched off"
        else:
            on[s.name] = s.default == "on"
            if not on[s.name]:
                off[s.name] = "off by default"
    changed = True
    while changed:                       # repeat: forcing one step off can force another off
        changed = False
        for s in lib.steps:
            if not on[s.name]:
                continue
            missing = [o for o in s.only_with if not on[o]]
            if missing:
                on[s.name] = False
                off[s.name] = f"needs {missing[0]}, which is off"
                changed = True
    return on, off


def _find_sources(lib: Library, active: list[Step],
                  off: dict[str, str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Rule 3: for every running step and need, the latest earlier producer, else provided, else fallback."""
    sources: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for step in active:
        sources[step.name] = {}
        for need in step.needs:
            source = _source_for(lib, active, step, need)
            if source is None:
                problems.append(_unmet(lib, step, need, off))
            else:
                sources[step.name][need] = source
    return sources, problems


def _source_for(lib: Library, active: list[Step], step: Step, need: str) -> str | None:
    """Where one need of one step comes from, or None when nothing can supply it."""
    earlier = [s for s in active if s.sort_key < step.sort_key and need in s.produces]
    if earlier:
        return f"step:{earlier[-1].name}"
    thing = lib.things[need]
    if thing.provided_for(step.group):
        return "provided"
    if thing.fallback:
        return f"fallback:{thing.fallback}"
    return None


def _unmet(lib: Library, step: Step, need: str, off: dict[str, str]) -> str:
    """Plain-English reason a need cannot be met, naming the off or later steps that make it."""
    makers = [s for s in lib.steps if need in s.produces and s.name != step.name]
    thing = lib.things[need]
    if thing.provided and not thing.provided_for(step.group):
        return (f"{step.title} ({step.name}) needs {need}, but Phoenix only provides {need} "
                f"to {thing.provided}-level steps.")
    head = f"{step.title} ({step.name}) needs {need}, and {need} has no fallback"
    off_makers = [s for s in makers if s.sort_key < step.sort_key]
    later = [s for s in makers if s.sort_key > step.sort_key]
    if off_makers:
        names = ", ".join(f"{s.name} ({off.get(s.name, 'off')})" for s in off_makers)
        fix = f", or switch off {step.name}" if step.can_switch_off else ""
        return f"{head}. Only {names} makes it earlier. Turn that back on{fix}."
    if later:
        names = ", ".join(s.name for s in later)
        return f"{head}: {names} makes it, but runs later. Nothing earlier makes it."
    return f"{head}, and no step in the library makes it."
