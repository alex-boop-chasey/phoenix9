"""The event stream: one JSON line per event, in the global file and in the run's own file."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import paths, scrub

# Allowed event types (docs/architecture.md section 8).
EVENT_TYPES = frozenset("""
run.queued run.started run.finished run.step.started run.step.finished task.started
task.finished gate.opened gate.answered project.created project.changed settings.changed
update.started update.installed update.safety_files_added update.failed update.rolledback deploy.finished run.held command
""".split())
EVENT_TYPES = EVENT_TYPES | {"run.discarded", "run.tidied", "project.deleted", "ui.go", "repair.applied", "repair.unlock", "run.note", "run.paused", "run.resumed", "run.pause.dropped", "edit.started", "edit.finished", "edit.abandoned", "edit.stalled", "plan.queued", "plan.started", "plan.continued", "plan.waiting", "plan.done", "plan.failed", "plan.abandoned", "update.safety_files_skipped", "agent.sync_skipped", "agent.restarted_for_rules", "suite.skipped", "reference.snapshot"}   # run.discarded: `phoenix run discard` threw a run's work away; run.tidied: `phoenix run tidy` removed a merged run's worktree and branches; project.deleted: a project was deleted entirely; run.pause.dropped: a stale Pause now request was thrown away


def _append(path: Path, line: str) -> None:
    """Append one line to a file with a single write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(scrub.scrub(line))
        f.flush()


def emit(type: str, *, project: str | None, run: str | None = None, task: int | None = None,
         step: str | None = None, **data) -> dict:
    """Record one event in HOME/events.jsonl and, when a run is given, in that run's events.jsonl."""
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type}")
    event = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "type": type,
             "project": project, "run": run, "task": task, "step": step, "data": data}
    line = json.dumps(event) + "\n"
    _append(paths.events(), line)
    if run and project:
        _append(paths.runs(project) / run / "events.jsonl", line)
    return event


def read(path: Path, after_line: int = 0) -> list[dict]:
    """Read events from a file, skipping the first after_line lines; a missing file gives []."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events = []
    for line in lines[after_line:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn or damaged line is skipped, not fatal
    return events


def tail(path: Path, n: int) -> list[dict]:
    """The last n events in a file."""
    if n <= 0:
        return []
    return read(path)[-n:]
