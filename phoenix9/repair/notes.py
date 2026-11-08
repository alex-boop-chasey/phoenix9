"""The repair note parser: read the strict markdown note a fixer writes, and write the result back into it."""
import re
from dataclasses import dataclass, field

TITLE_RE = re.compile(r"^# Repair (\S+)\s*$")
WORD = r"[A-Za-z0-9_.:-]+"
STEP_FORMS = [
    ("redo", re.compile(r"redo task (?P<n>\d+) from scratch")),
    ("mark-done", re.compile(r"mark task (?P<n>\d+) done because (?P<why>\S.*)")),
    ("mark-skipped", re.compile(r"mark task (?P<n>\d+) skipped because (?P<why>\S.*)")),
    ("retry", re.compile(r"retry task (?P<n>\d+)")),
    ("clear-failures", re.compile(r"clear failures of task (?P<n>\d+)")),
    ("add-note", re.compile(r"add a note to task (?P<n>\d+): (?P<text>\S.*)")),
    ("set-setting", re.compile(r"set (?P<key>[A-Za-z_][\w-]*(?:\.[\w-]+)*)=(?P<value>\S.*?) for this run")),
    ("turn-off-step", re.compile(rf"turn off step (?P<name>{WORD}) for this run")),
    ("replace-spec", re.compile(r"replace the spec with (?P<path>\S+)")),
    ("keep-hand-fix", re.compile(r'keep my hand fix with message "(?P<message>[^"]+)"')),
    ("reset-worktree", re.compile(r"reset the worktree to (?P<sha>[0-9a-fA-F]{4,40})")),
    ("rebuild-worktree", re.compile(r"rebuild the worktree")),
    ("close-question", re.compile(rf"close question (?P<id>{WORD}) as (?P<action>{WORD})")),
    ("rewrite-checks", re.compile(r"rewrite the checks of task (?P<n>\d+) because (?P<why>\S.*)")),
    ("rerun-finish", re.compile(rf"rerun finish step (?P<name>{WORD})")),
    ("resume", re.compile(r"resume")),
]
INT_ARGS = ("n",)


class NoteError(ValueError):
    """A repair note that cannot be read; the message says why, with the line number when there is one."""

    def __init__(self, message, line=None):
        super().__init__(message)
        self.line = line


@dataclass
class Step:
    """One step of a note: its kind, its arguments, its line number and its original text."""
    kind: str
    args: dict
    line: int
    text: str


@dataclass
class Note:
    """A parsed repair note."""
    run: str
    why: str
    steps: list = field(default_factory=list)
    force: bool = False


def parse_step(text, line):
    """Turn one step text into a Step, or refuse it with its line number."""
    for kind, rx in STEP_FORMS:
        m = rx.fullmatch(text)
        if m:
            args = {k: int(v) if k in INT_ARGS else v for k, v in m.groupdict().items()}
            return Step(kind, args, line, text)
    raise NoteError(f"line {line}: I do not know this step: {text}", line)


def parse(text) -> Note:
    """Read a repair note; refuse anything unknown or missing."""
    run, why, section, steps, force, seen_steps = None, None, None, [], False, False
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.startswith("## "):
            name = line[3:].strip()
            section = name.lower() if name.lower() in ("steps", "result") else "other"
            seen_steps = seen_steps or section == "steps"
            continue
        if run is None and section is None and line.startswith("# "):
            m = TITLE_RE.match(line)
            if not m:
                raise NoteError(f"line {no}: the title must be '# Repair <run>': {line}", no)
            run = m.group(1)
        elif section is None and line.startswith("Why:") and why is None:
            why = line[4:].strip()
        elif section == "steps" and line.strip():
            if not line.startswith("- "):
                raise NoteError(f"line {no}: a step must start with '- ': {line}", no)
            body = line[2:].strip()
            if body == "force":
                force = True
            else:
                steps.append(parse_step(body, no))
    if run is None:
        raise NoteError("the note has no '# Repair <run>' title")
    if not why:
        raise NoteError("the note has no 'Why:' line")
    if not seen_steps or not (steps or force):
        raise NoteError("the note has no '## Steps' list with steps")
    return Note(run, why, steps, force)


def result_text(result) -> str:
    """Plain text for a result given as text, a list of lines or a dict."""
    if isinstance(result, dict):
        return "\n".join(f"- {k}: {v}" for k, v in result.items())
    if isinstance(result, (list, tuple)):
        return "\n".join(str(x) for x in result)
    return str(result).strip("\n")


def render_result(note_text, result) -> str:
    """Replace the '## Result' section of a note with this result, or append one."""
    section = "## Result\n\n" + result_text(result) + "\n"
    lines = note_text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.rstrip().lower() == "## result"), None)
    if start is None:
        return note_text.rstrip("\n") + "\n\n" + section
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    before = "\n".join(lines[:start]).rstrip("\n")
    after = "\n".join(lines[end:])
    return before + "\n\n" + section + ("\n" + after + "\n" if after else "")
