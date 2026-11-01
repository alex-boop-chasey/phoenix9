"""Read a hand-written plan.md into steps, and check it against the plan rules.

`parse(text)` never raises on a badly written plan: it records what it could
not understand in `Plan.problems`. `check(plan)` returns those problems plus
every broken rule, as notes a person can act on. An empty list means the plan
is fine.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

MAX_STEPS = 60
MIN_BULLET = 15
VAGUE_ENDINGS = ("professional", "nice", "good", "clean", "modern", "works well")
SETUP_WORDS = ("set up", "setup", "scaffold", "create the project")

# Borrowed from Phoenix 0.6.0 hands/planner.py:46
HOST = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

TITLE_LINE = re.compile(r"^# Plan:\s*(.*?)\s*$")
SECTION = re.compile(r"^##(?!#)\s*(.*?)\s*$")
STEP_HEADING = re.compile(r"^Step\s+(\d+)\s*(?::\s*(.*?))?\s*$", re.IGNORECASE)
WORD_LINE = re.compile(r"^([A-Za-z][A-Za-z '-]*?)\s*:\s*(.*?)\s*$")
HEADER_KEYS = {
    "type": "type",
    "repo": "repo",
    "stack": "stack",
    "style": "style",
    "sites the app may contact": "sites",
}
STEP_OPTIONS = {
    "depends on": "depends_on",
    "for you": "for_you",
    "changes existing behaviour": "changes_behaviour",
    "changes existing behavior": "changes_behaviour",
}
VAGUE = re.compile(r"(?:^|\W)(" + "|".join(re.escape(w) for w in VAGUE_ENDINGS) + r")$")


@dataclass
class Step:
    """One `## Step <n>: <title>` section of a plan."""

    number: int
    title: str
    description: str
    done_when: list[str]
    depends_on: list[int]
    for_you: bool
    changes_behaviour: bool
    text_hash: str
    line: int = 0                                         # line of the `## Step` heading
    depends_line: int = 0                                 # line of `Depends on:` (0 = not written)
    done_when_lines: list[int] = field(default_factory=list)


@dataclass
class Plan:
    """A whole plan.md: header settings, free text sections, and steps."""

    name: str = ""
    type: str = ""
    repo: str = ""
    stack: str = ""
    style: str = ""
    sites: list[str] = field(default_factory=list)
    about: str = ""
    every_step: str = ""
    steps: list[Step] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)    # things parse() could not understand
    header_lines: dict[str, int] = field(default_factory=dict)
    has_about: bool = False


def _where(step: int | None, line: int) -> str:
    """Return the start of an error note, e.g. 'Step 3 (line 27)' or 'Line 4'."""
    return f"Step {step} (line {line})" if step is not None else f"Line {line}"


def _split_sections(lines: list[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str, list[tuple[int, str]]]]]:
    """Split the plan into the header lines and the `##` sections.

    Returns (header, sections). Line numbers start at 1. Each section is
    (heading line number, heading text, [(line number, line), ...]).
    """
    header: list[tuple[int, str]] = []
    sections: list[tuple[int, str, list[tuple[int, str]]]] = []
    for number, line in enumerate(lines, start=1):
        if number == 1:
            continue
        m = SECTION.match(line)
        if m:
            sections.append((number, m.group(1), []))
        elif sections:
            sections[-1][2].append((number, line))
        else:
            header.append((number, line))
    return header, sections


def _free_text(body: list[tuple[int, str]]) -> str:
    """Join a section's lines into one block of text without leading/trailing blank lines."""
    return "\n".join(line for _, line in body).strip()


def _parse_header(plan: Plan, header: list[tuple[int, str]]) -> None:
    """Read the `Word: value` lines that come before the first `##` section."""
    for number, line in header:
        if not line.strip():
            continue
        m = WORD_LINE.match(line.strip())
        key = HEADER_KEYS.get(m.group(1).lower()) if m else None
        if key is None:
            if m:
                plan.problems.append(
                    f"Line {number}: '{m.group(1)}:' is not a header Phoenix knows. "
                    "Before the first '##' only Type, Repo, Stack, Style and "
                    "'Sites the app may contact' are allowed.")
            else:
                plan.problems.append(
                    f"Line {number}: text before the first '##' section must be a header line "
                    f"like 'Type: new'. Move '{line.strip()[:40]}' into '## About' or a step.")
            continue
        if key in plan.header_lines:
            plan.problems.append(
                f"Line {number}: '{m.group(1)}:' is written twice "
                f"(first at line {plan.header_lines[key]}). Keep one.")
            continue
        plan.header_lines[key] = number
        value = m.group(2)
        if key == "sites":
            plan.sites = [s.strip() for s in value.split(",")] if value else []
        else:
            setattr(plan, key, value)


def _parse_option(step: Step, key: str, value: str, number: int, problems: list[str]) -> None:
    """Fill in one of a step's optional lines: Depends on, For you, Changes existing behaviour."""
    where = _where(step.number, number)
    if key == "depends_on":
        step.depends_line = number
        if value.lower() == "none":
            step.depends_on = []
            return
        parts = [p.strip() for p in value.split(",")]
        if not value or not all(p.isdigit() for p in parts):
            problems.append(
                f"{where}: 'Depends on:' should list step numbers separated by commas, "
                f"like 'Depends on: 1, 3' (or 'none'), not '{value}'.")
            return
        step.depends_on = [int(p) for p in parts]
        return
    if value.lower() not in ("yes", "no"):
        label = "For you" if key == "for_you" else "Changes existing behaviour"
        problems.append(f"{where}: '{label}:' should be 'yes' or 'no', not '{value}'.")
        return
    setattr(step, key, value.lower() == "yes")


def _parse_step(number: int, title: str, heading_line: int, heading: str,
                body: list[tuple[int, str]], problems: list[str]) -> Step:
    """Turn one `## Step` section into a Step, noting anything it cannot read."""
    raw = "\n".join([heading] + [line for _, line in body]).rstrip() + "\n"
    step = Step(number=number, title=title, description="", done_when=[],
                depends_on=[number - 1] if number > 1 else [], for_you=False,
                changes_behaviour=False, text_hash=hashlib.sha256(raw.encode()).hexdigest(),
                line=heading_line)
    description: list[str] = []
    in_done = False
    seen: dict[str, int] = {}
    for line_no, line in body:
        stripped = line.strip()
        if in_done:
            if not stripped:
                continue
            if stripped.startswith("- ") or stripped == "-":
                step.done_when.append(stripped[1:].strip())
                step.done_when_lines.append(line_no)
            elif line[:1].isspace() and step.done_when:
                step.done_when[-1] += " " + stripped          # wrapped bullet
            else:
                problems.append(
                    f"{_where(number, line_no)}: after 'Done when:' only '- ' bullets are allowed "
                    f"until the next '##'. Found '{stripped[:40]}'.")
            continue
        if re.match(r"^done when\s*:", stripped, re.IGNORECASE):
            in_done = True
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                problems.append(
                    f"{_where(number, line_no)}: put each 'Done when' item on its own line "
                    "starting with '- ', below 'Done when:'.")
            continue
        m = WORD_LINE.match(stripped)
        key = STEP_OPTIONS.get(m.group(1).lower()) if m else None
        if key:
            if key in seen:
                problems.append(
                    f"{_where(number, line_no)}: '{m.group(1)}:' is written twice "
                    f"(first at line {seen[key]}). Keep one.")
                continue
            seen[key] = line_no
            _parse_option(step, key, m.group(2), line_no, problems)
            continue
        description.append(line)
    step.description = "\n".join(description).strip()
    return step


def parse(text: str) -> Plan:
    """Read plan.md text into a Plan. Anything unreadable goes into Plan.problems."""
    plan = Plan()
    lines = text.splitlines()
    m = TITLE_LINE.match(lines[0]) if lines else None
    if m and m.group(1):
        plan.name = m.group(1)
    else:
        plan.problems.append("Line 1: the plan must start with '# Plan: <name>'.")
    header, sections = _split_sections(lines)
    _parse_header(plan, header)
    seen: dict[str, int] = {}
    for number, heading, body in sections:
        sm = STEP_HEADING.match(heading)
        if sm:
            plan.steps.append(_parse_step(int(sm.group(1)), sm.group(2) or "", number,
                                          lines[number - 1], body, plan.problems))
            continue
        kind = heading.lower()
        if kind not in ("about", "every step"):
            plan.problems.append(
                f"Line {number}: '## {heading}' is not a section Phoenix knows. "
                "Use '## About', '## Every step' or '## Step <n>: <title>'.")
            continue
        if kind in seen:
            plan.problems.append(f"Line {number}: '## {heading}' appears twice (first at line {seen[kind]}).")
            continue
        seen[kind] = number
        if kind == "about":
            plan.has_about = True
            plan.about = _free_text(body)
        else:
            plan.every_step = _free_text(body)
    return plan


def _check_header(plan: Plan) -> list[str]:
    """Check Type, Repo, About and the allowed sites."""
    errors = []
    if not plan.type:
        errors.append("The header is missing 'Type: new' or 'Type: change'.")
    elif plan.type not in ("new", "change"):
        errors.append(f"Line {plan.header_lines['type']}: 'Type:' must be 'new' or 'change', not '{plan.type}'.")
    if not plan.repo:
        errors.append("The header is missing 'Repo: <owner>/<name>'.")
    elif not REPO.match(plan.repo):
        errors.append(f"Line {plan.header_lines['repo']}: 'Repo:' must look like 'owner/name', not '{plan.repo}'.")
    for host in plan.sites:
        if not HOST.match(host):
            hint = " Write hostnames in lowercase." if HOST.match(host.lower()) else ""
            shown = host or "(empty)"
            errors.append(
                f"Line {plan.header_lines['sites']}: '{shown}' in 'Sites the app may contact' is not a "
                f"plain hostname like 'api.example.com' (no https://, paths, ports or spaces).{hint}")
    if not plan.has_about:
        errors.append("The plan has no '## About' section. Add one with a few lines about the site.")
    elif not plan.about:
        errors.append("The '## About' section is empty. Say in a few lines what the site is.")
    return errors


def _check_numbers(plan: Plan) -> list[str]:
    """Rule 1: steps are numbered 1..n with no gaps or repeats, at most 60."""
    errors = []
    if not plan.steps:
        return ["The plan has no steps. Add sections like '## Step 1: Set up the project'."]
    first: dict[int, int] = {}
    for step in plan.steps:
        if step.number in first:
            errors.append(f"Step {step.number} (line {step.line}): step {step.number} is used twice "
                          f"(first at line {first[step.number]}). Give each step its own number.")
        else:
            first[step.number] = step.line
    expected = 1
    for step in plan.steps:
        if step.number in first and first[step.number] != step.line:
            continue
        if step.number != expected:
            errors.append(f"Step {step.number} (line {step.line}): steps must be numbered 1, 2, 3 … "
                          f"in order with no gaps; expected step {expected} here.")
            break
        expected += 1
    if len(first) > MAX_STEPS:
        errors.append(f"The plan has {len(first)} steps; the most allowed is {MAX_STEPS}. Split it into two plans.")
    return errors


def _check_step(step: Step) -> list[str]:
    """Rules 2, 3 and 5 for one step."""
    errors = []
    where = _where(step.number, step.line)
    if not step.title:
        errors.append(f"{where}: the step has no title. Write it as '## Step {step.number}: <title>'.")
    if not step.description:
        errors.append(f"{where}: the step has no description. Say what the builder should do.")
    if not step.done_when and not step.for_you:
        errors.append(f"{where}: the step has no 'Done when:' list. Add at least one '- ' bullet "
                      "saying how to tell the step is finished.")
    for dep in step.depends_on:
        if dep >= step.number:
            errors.append(f"{_where(step.number, step.depends_line or step.line)}: 'Depends on' names step "
                          f"{dep}, but a step can only depend on earlier steps.")
        elif dep < 1:
            errors.append(f"{_where(step.number, step.depends_line or step.line)}: 'Depends on' names step "
                          f"{dep}, which does not exist.")
    for bullet, line in zip(step.done_when, step.done_when_lines):
        if len(bullet) < MIN_BULLET:
            errors.append(f"{_where(step.number, line)}: the 'Done when' item '{bullet}' is too short "
                          f"(under {MIN_BULLET} characters). Say exactly what can be checked.")
            continue
        m = VAGUE.search(bullet.lower().rstrip(" .!,;:"))
        if m:
            errors.append(f"{_where(step.number, line)}: the 'Done when' item '{bullet}' ends with the vague "
                          f"word '{m.group(1)}'. Say what can be checked instead.")
    return errors


def _check_setup(plan: Plan) -> list[str]:
    """Rule 4: a `Type: new` plan starts by setting up the project."""
    if plan.type != "new":
        return []
    first = next((s for s in plan.steps if s.number == 1), None)
    if first is None:
        return []
    text = f"{first.title}\n{first.description}".lower()
    if any(word in text for word in SETUP_WORDS):
        return []
    return [f"Step 1 (line {first.line}): this is a 'Type: new' plan, so step 1 must set up the project. "
            "Its title or description should say 'set up', 'setup', 'scaffold' or 'create the project'."]


def check(plan: Plan) -> list[str]:
    """Return every problem with the plan as a readable note. Empty list = the plan is valid."""
    errors = list(plan.problems)
    errors += _check_header(plan)
    errors += _check_numbers(plan)
    for step in plan.steps:
        errors += _check_step(step)
    errors += _check_setup(plan)
    numbers = {s.number for s in plan.steps}
    for step in plan.steps:
        for dep in step.depends_on:
            if 1 <= dep < step.number and dep not in numbers:
                errors.append(f"{_where(step.number, step.depends_line or step.line)}: 'Depends on' "
                              f"names step {dep}, which is not in the plan.")
    return errors


def plan_order(plan: Plan) -> list[Step]:
    """Return the steps sorted by step number."""
    return sorted(plan.steps, key=lambda s: s.number)


def dependents_of(plan: Plan, n: int) -> list[Step]:
    """Return every step that depends on step n, directly or through other steps, in number order."""
    found: set[int] = set()
    todo = [n]
    while todo:
        current = todo.pop()
        for step in plan.steps:
            if current in step.depends_on and step.number not in found and step.number != n:
                found.add(step.number)
                todo.append(step.number)
    return [s for s in plan_order(plan) if s.number in found]
