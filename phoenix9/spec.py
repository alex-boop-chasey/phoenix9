"""Read a hand-written spec (markdown) into tasks, check it, and convert it to and from spec.json.

# ported from reference/v8/phoenix/plan.py (generalised: tasks instead of steps, no web-only keys)

`parse(text)` never raises on a badly written spec; `check(text)` returns plain-English problems
with line numbers. An empty list means the spec is fine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from phoenix9.settings import PRESETS

MAX_TASKS = 60
MAX_DESCRIPTION_BYTES = 200_000                         # any spec when the Planner is on (a description)
NEEDS_PLANNER = ("This spec isn't in Phoenix's task format. Turn the Planner on so it can turn it into tasks, "
                 "or write it as '## Task <n>: <title>' sections.")
MIN_BULLET = 15
VAGUE_ENDINGS = ("professional", "nice", "good", "clean", "modern", "works well")

TITLE_LINE = re.compile(r"^#(?!#)\s*(?:Plan:\s*)?(.*?)\s*$")
SECTION = re.compile(r"^##(?!#)\s*(.*?)\s*$")
TASK_HEADING = re.compile(r"^(?:Task|Step)\s+(\d+)\s*(?::\s*(.*?))?\s*$", re.IGNORECASE)
WORD_LINE = re.compile(r"^([A-Za-z][A-Za-z '-]*?)\s*:\s*(.*?)\s*$")
HEADER_KEYS = {"project": "project", "preset": "preset"}
IGNORED_HEADER_KEYS = ("type", "repo", "stack", "style", "sites the app may contact")  # V8 keys
TASK_OPTIONS = {"depends on": "depends_on", "for you": "for_you"}
COMMAND_BULLET = re.compile(r"^`([^`]+)`$")
VAGUE = re.compile(r"(?:^|\W)(" + "|".join(re.escape(w) for w in VAGUE_ENDINGS) + r")$")


@dataclass
class Check:
    """One 'Done when' bullet; `command` is set when the whole bullet is one backticked command."""

    text: str
    command: str | None = None


@dataclass
class Task:
    """One `## Task <n>: <title>` section."""

    number: int
    title: str
    goal: str
    depends_on: list[int]
    for_you: bool
    done_when: list[Check]
    line: int = 0                                         # line of the heading
    depends_line: int = 0                                 # line of `Depends on:` (0 = not written)
    done_when_lines: list[int] = field(default_factory=list)


@dataclass
class Spec:
    """A whole spec: header, About text and tasks."""

    title: str
    project: str
    preset: str
    about: str
    tasks: list[Task]
    problems: list[str] = field(default_factory=list)    # things parse() could not understand
    has_about: bool = False
    header_lines: dict[str, int] = field(default_factory=dict)


def _where(task: int | None, line: int) -> str:
    """Return the start of a problem note, e.g. 'Task 3 (line 27)' or 'Line 4'."""
    return f"Task {task} (line {line})" if task is not None else f"Line {line}"


def _split_sections(lines: list[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str, list[tuple[int, str]]]]]:
    """Split into header lines and `##` sections (line numbers start at 1; line 1 is the title)."""
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


def _parse_header(spec: Spec, header: list[tuple[int, str]]) -> None:
    """Read the `Word: value` lines before the first `##` section."""
    seen: dict[str, int] = {}
    for number, line in header:
        if not line.strip():
            continue
        m = WORD_LINE.match(line.strip())
        word = m.group(1).lower() if m else ""
        if m and word in IGNORED_HEADER_KEYS:
            continue
        key = HEADER_KEYS.get(word)
        if key is None:
            if m:
                spec.problems.append(
                    f"Line {number}: '{m.group(1)}:' is not a header Phoenix knows. "
                    "Before the first '##' only Project and Preset are used.")
            else:
                spec.problems.append(
                    f"Line {number}: text before the first '##' section must be a header line "
                    f"like 'Project: name'. Move '{line.strip()[:40]}' into '## About' or a task.")
            continue
        if key in seen:
            spec.problems.append(f"Line {number}: '{m.group(1)}:' is written twice (first at line {seen[key]}). Keep one.")
            continue
        seen[key] = number
        setattr(spec, key, m.group(2))
    spec.header_lines = seen


def _parse_option(task: Task, key: str, value: str, number: int, problems: list[str]) -> None:
    """Fill in a task's `Depends on` or `For you` line."""
    where = _where(task.number, number)
    if key == "depends_on":
        task.depends_line = number
        if value.lower() == "none":
            task.depends_on = []
            return
        parts = [p.strip() for p in value.split(",")]
        if not value or not all(p.isdigit() for p in parts):
            problems.append(f"{where}: 'Depends on:' should list task numbers separated by commas, "
                            f"like 'Depends on: 1, 3' (or 'none'), not '{value}'.")
            return
        task.depends_on = [int(p) for p in parts]
        return
    if value.lower() not in ("yes", "no"):
        problems.append(f"{where}: 'For you:' should be 'yes' or 'no', not '{value}'.")
        return
    task.for_you = value.lower() == "yes"


def _make_check(bullet: str) -> Check:
    """Turn bullet text into a Check, extracting the command when the bullet is one backticked command."""
    m = COMMAND_BULLET.match(bullet)
    return Check(bullet, m.group(1).strip() if m else None)


def _parse_task(number: int, title: str, heading_line: int, body: list[tuple[int, str]],
                problems: list[str]) -> Task:
    """Turn one task section into a Task, noting anything unreadable."""
    task = Task(number=number, title=title, goal="", depends_on=[number - 1] if number > 1 else [],
                for_you=False, done_when=[], line=heading_line)
    goal: list[str] = []
    in_done = False
    seen: dict[str, int] = {}
    for line_no, line in body:
        stripped = line.strip()
        if in_done:
            if not stripped:
                continue
            if stripped.startswith("- ") or stripped == "-":
                task.done_when.append(_make_check(stripped[1:].strip()))
                task.done_when_lines.append(line_no)
            elif line[:1].isspace() and task.done_when:
                joined = task.done_when[-1].text + " " + stripped        # wrapped bullet
                task.done_when[-1] = _make_check(joined)
            else:
                problems.append(f"{_where(number, line_no)}: after 'Done when:' only '- ' bullets are allowed "
                                f"until the next '##'. Found '{stripped[:40]}'.")
            continue
        if re.match(r"^done when\s*:", stripped, re.IGNORECASE):
            in_done = True
            if stripped.split(":", 1)[1].strip():
                problems.append(f"{_where(number, line_no)}: put each 'Done when' item on its own line "
                                "starting with '- ', below 'Done when:'.")
            continue
        m = WORD_LINE.match(stripped)
        key = TASK_OPTIONS.get(m.group(1).lower()) if m else None
        if key:
            if key in seen:
                problems.append(f"{_where(number, line_no)}: '{m.group(1)}:' is written twice "
                                f"(first at line {seen[key]}). Keep one.")
                continue
            seen[key] = line_no
            _parse_option(task, key, m.group(2), line_no, problems)
            continue
        goal.append(line)
    task.goal = "\n".join(goal).strip()
    return task


PLAN_SECTIONS = ("open questions", "decisions")


def parse(text: str) -> Spec:
    """Read spec markdown into a Spec. Anything unreadable goes into Spec.problems."""
    spec = Spec(title="", project="", preset="", about="", tasks=[])
    lines = text.splitlines()
    m = TITLE_LINE.match(lines[0]) if lines else None
    if m and m.group(1):
        spec.title = m.group(1)
    else:
        spec.problems.append("Line 1: the spec must start with '# <title>'.")
    header, sections = _split_sections(lines)
    _parse_header(spec, header)
    seen: dict[str, int] = {}
    for number, heading, body in sections:
        tm = TASK_HEADING.match(heading)
        if tm:
            spec.tasks.append(_parse_task(int(tm.group(1)), tm.group(2) or "", number, body, spec.problems))
        elif heading.lower() == "about":
            if "about" in seen:
                spec.problems.append(f"Line {number}: '## {heading}' appears twice (first at line {seen['about']}).")
                continue
            seen["about"] = number
            spec.has_about = True
            spec.about = "\n".join(line for _, line in body).strip()
        elif heading.lower() in PLAN_SECTIONS:       # a planning session's questions and decisions (not used by runs)
            key = heading.lower()
            if key in seen:
                spec.problems.append(f"Line {number}: '## {heading}' appears twice (first at line {seen[key]}).")
                continue
            seen[key] = number
        else:
            spec.problems.append(f"Line {number}: '## {heading}' is not a section Phoenix knows. "
                                 "Use '## About' or '## Task <n>: <title>'.")
    return spec


def _check_numbers(spec: Spec) -> list[str]:
    """Tasks are numbered 1..n with no gaps or repeats, at most 60, at least one."""
    if not spec.tasks:
        return ["The spec has no tasks. Add sections like '## Task 1: Set up the project'."]
    errors = []
    first: dict[int, int] = {}
    for t in spec.tasks:
        if t.number in first:
            errors.append(f"Task {t.number} (line {t.line}): task {t.number} is used twice "
                          f"(first at line {first[t.number]}). Give each task its own number.")
        else:
            first[t.number] = t.line
    expected = 1
    for t in spec.tasks:
        if first[t.number] != t.line:
            continue
        if t.number != expected:
            errors.append(f"Task {t.number} (line {t.line}): tasks must be numbered 1, 2, 3 … "
                          f"in order with no gaps; expected task {expected} here.")
            break
        expected += 1
    if len(first) > MAX_TASKS:
        errors.append(f"The spec has {len(first)} tasks; the most allowed is {MAX_TASKS}. Split it into two specs.")
    return errors


def _check_bullets(task: Task) -> list[str]:
    """Check each 'Done when' bullet for length and vague endings (commands are exempt)."""
    errors = []
    for check, line in zip(task.done_when, task.done_when_lines):
        if check.command is not None:
            continue
        bullet = check.text
        if len(bullet) < MIN_BULLET:
            errors.append(f"{_where(task.number, line)}: the 'Done when' item '{bullet}' is too short "
                          f"(under {MIN_BULLET} characters). Say exactly what can be checked.")
            continue
        m = VAGUE.search(bullet.lower().rstrip(" .!,;:"))
        if m:
            errors.append(f"{_where(task.number, line)}: the 'Done when' item '{bullet}' ends with the vague "
                          f"word '{m.group(1)}'. Say what can be checked instead.")
    return errors


def _check_task(task: Task, numbers: set[int]) -> list[str]:
    """Title, goal, done-when and dependency rules for one task."""
    errors = []
    where = _where(task.number, task.line)
    if not task.title:
        errors.append(f"{where}: the task has no title. Write it as '## Task {task.number}: <title>'.")
    if not task.goal:
        errors.append(f"{where}: the task has no description. Say what the builder should do.")
    if not task.done_when and not task.for_you:
        errors.append(f"{where}: the task has no 'Done when:' list. Add at least one '- ' bullet "
                      "saying how to tell the task is finished.")
    dep_where = _where(task.number, task.depends_line or task.line)
    for dep in task.depends_on:
        if dep >= task.number:
            errors.append(f"{dep_where}: 'Depends on' names task {dep}, but a task can only depend on earlier tasks.")
        elif dep not in numbers:
            errors.append(f"{dep_where}: 'Depends on' names task {dep}, which is not in the spec.")
    return errors + _check_bullets(task)


def _find_cycle(spec: Spec) -> list[int]:
    """Return the task numbers of one dependency cycle, or [] when there is none."""
    known = {t.number for t in spec.tasks}
    graph = {t.number: [d for d in t.depends_on if d in known and d != t.number] for t in spec.tasks}
    state: dict[int, int] = {}
    stack: list[int] = []

    def visit(n: int) -> list[int]:
        state[n] = 1
        stack.append(n)
        for d in graph[n]:
            if state.get(d) == 1:
                return stack[stack.index(d):] + [d]
            if d not in state:
                found = visit(d)
                if found:
                    return found
        stack.pop()
        state[n] = 2
        return []

    for n in graph:
        if n not in state:
            found = visit(n)
            if found:
                return found
    return []


def check(text: str) -> list[str]:
    """Return every problem with the spec as a readable note. Empty list = the spec is valid."""
    spec = parse(text)
    errors = list(spec.problems)
    if spec.preset and spec.preset not in PRESETS:
        line = spec.header_lines.get("preset", 1)
        errors.append(f"Line {line}: 'Preset: {spec.preset}' is not a preset Phoenix knows. "
                      f"Use one of: {', '.join(PRESETS)}.")
    errors += _check_numbers(spec)
    numbers = {t.number for t in spec.tasks}
    for t in spec.tasks:
        errors += _check_task(t, numbers)
    cycle = _find_cycle(spec)
    if cycle:
        errors.append("The tasks depend on each other in a cycle: "
                      + " -> ".join(f"task {n}" for n in cycle) + ". Break the loop in 'Depends on'.")
    return errors


def check_description(text: str) -> list[str]:
    """Problems with a spec when the Planner is on: any text is a description for it, so only empty or too big is wrong."""
    if not text.strip():
        return ["The description is empty. Say what should be built."]
    size = len(text.encode("utf-8"))
    if size > MAX_DESCRIPTION_BYTES:
        return [f"The description is {size // 1000} KB; the most allowed is {MAX_DESCRIPTION_BYTES // 1000} KB. "
                "Shorten it or split it into two."]
    return []


def description_title(text: str, fallback: str = "") -> str:
    """A title for a free-form description: its `# title`, else its first heading or line (cut), else `fallback`."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            title = re.sub(r"^(?:#+\s*)?(?:Plan:\s*)?", "", line).strip()
            if title:
                return title[:80]
    return fallback


def order(spec: Spec) -> list[Task]:
    """Return the tasks in an order where each comes after the tasks it depends on (lowest number first)."""
    by_number = {t.number: t for t in spec.tasks}
    done: list[int] = []
    waiting = sorted(by_number)
    while waiting:
        ready = [n for n in waiting if all(d in done or d not in by_number for d in by_number[n].depends_on)]
        if not ready:                       # a cycle: keep number order for the rest
            ready = [waiting[0]]
        done.append(ready[0])
        waiting.remove(ready[0])
    return [by_number[n] for n in done]


def dependents_of(spec: Spec, n: int) -> list[Task]:
    """Return every task that depends on task n, directly or through other tasks, in number order."""
    found: set[int] = set()
    todo = [n]
    while todo:
        current = todo.pop()
        for t in spec.tasks:
            if current in t.depends_on and t.number not in found and t.number != n:
                found.add(t.number)
                todo.append(t.number)
    return sorted((t for t in spec.tasks if t.number in found), key=lambda t: t.number)


def to_json(spec: Spec) -> dict:
    """Turn a Spec into plain data for spec.json."""
    return {
        "title": spec.title, "project": spec.project, "preset": spec.preset, "about": spec.about,
        "tasks": [{
            "number": t.number, "title": t.title, "goal": t.goal, "depends_on": list(t.depends_on),
            "for_you": t.for_you,
            "done_when": [{"text": c.text, "command": c.command} for c in t.done_when],
        } for t in spec.tasks],
    }


def from_json(d: dict) -> Spec:
    """Rebuild a Spec from the data written by `to_json`."""
    tasks = [Task(number=t["number"], title=t["title"], goal=t["goal"], depends_on=list(t["depends_on"]),
                  for_you=t["for_you"],
                  done_when=[Check(c["text"], c.get("command")) for c in t["done_when"]])
             for t in d["tasks"]]
    return Spec(title=d["title"], project=d["project"], preset=d["preset"], about=d["about"], tasks=tasks)
