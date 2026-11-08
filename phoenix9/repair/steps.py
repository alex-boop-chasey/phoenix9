"""The repair note steps: one function per step, and the registry the apply engine looks them up in."""
from dataclasses import dataclass

from phoenix9 import scrub, state


class StepRefused(Exception):
    """A step cannot be done; the message says why in plain words."""


@dataclass
class Context:
    """What a step is given: the run folder to change (a scratch copy in a dry run) and how it was asked."""
    run_dir: object
    dry: bool = False
    approve_unlock: bool = False


def _task(ctx, n: int) -> dict:
    """The state entry of task n, or refuse when the run has no such task."""
    task = (state.load(ctx.run_dir).get("tasks") or {}).get(str(n))
    if task is None:
        raise StepRefused(f"task {n} is not in this run")
    return task


def _unwaiting(ctx, n: int) -> None:
    """Refuse when task n waits on an open question (close the question first)."""
    if _task(ctx, n).get("gate"):
        raise StepRefused(f"task {n} is waiting on a question; close the question first")


def _skip_dependents(st: dict, n: int, why: str) -> list[int]:
    """Skip every unfinished task that needs task n, directly or through others; return their numbers."""
    tasks, skipped, todo = st["tasks"], [], [str(n)]
    while todo:
        cur = todo.pop()
        for key, t in sorted(tasks.items(), key=lambda kv: int(kv[0])):
            if cur in [str(d) for d in t.get("depends_on") or []] and key not in todo and int(key) not in skipped:
                if t.get("status") in ("pending", "running", "waiting"):
                    t.update(status="skipped", gate=None, note=why)
                    skipped.append(int(key))
                todo.append(key)
    return sorted(skipped)


def mark_done(ctx, n: int, why: str) -> str:
    """Mark task n passed, with the reason as its note and its flag cleared."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(
        status="passed", note=scrub.scrub(why), flagged="", gate=None, rerun=False))
    return f"task {n} is now done ({scrub.scrub(why)})"


def mark_skipped(ctx, n: int, why: str) -> str:
    """Mark task n skipped, and skip the unfinished tasks that depend on it."""
    _unwaiting(ctx, n)
    skipped = []

    def change(s):
        s["tasks"][str(n)].update(status="skipped", note=scrub.scrub(why), gate=None, rerun=False)
        skipped.extend(_skip_dependents(s, n, f"depends on task {n}, which was skipped"))
    state.update(ctx.run_dir, change)
    more = f"; also skipped task {', '.join(map(str, skipped))}" if skipped else ""
    return f"task {n} is now skipped ({scrub.scrub(why)}){more}"


def retry(ctx, n: int) -> str:
    """Put task n back to pending with rerun on, keeping its failures."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(status="pending", rerun=True, flagged=""))
    return f"task {n} will run again (its earlier failures are kept)"


def clear_failures(ctx, n: int) -> str:
    """Forget the failure reasons of task n."""
    count = len(_task(ctx, n).get("failures") or [])
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(failures=[]))
    return f"cleared {count} failure(s) of task {n}"


def add_note(ctx, n: int, text: str) -> str:
    """Add a note to the failures of task n, which the next attempt reads."""
    line = "Note from the repair: " + scrub.scrub(text)
    _task(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].setdefault("failures", []).append(line))
    return f"added a note to task {n}"


STEPS = {"mark-done": mark_done, "mark-skipped": mark_skipped, "retry": retry,
         "clear-failures": clear_failures, "add-note": add_note}


def run_step(ctx, step) -> str:
    """Do one parsed step; refuse the ones that are not built yet. Returns what it changed, in words."""
    fn = STEPS.get(step.kind)
    if fn is None:
        raise StepRefused(f"'{step.text}' is not supported yet")
    return fn(ctx, **step.args)
