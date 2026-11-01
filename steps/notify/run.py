"""Notify: sends Alex one message about how the run ended (also when the run was stopped)."""
from phoenix9 import atomic, scrub, state
from phoenix9.stepctx import StepResult

STOPPED_NOTE = "the run was stopped"


def _counts(tasks: dict) -> tuple:
    """(passed, failed, skipped) task counts."""
    count = lambda status: sum(1 for t in tasks.values() if t.get("status") == status)  # noqa: E731
    return count("passed"), count("failed"), count("skipped")


def _outcome(st: dict) -> str:
    """'finished', 'stopped' or 'failed: <reason>' from the (maybe partial) state."""
    tasks = (st.get("tasks") or {}).values()
    if st.get("status") == "stopped" or any(t.get("note") == STOPPED_NOTE for t in tasks):
        return "stopped"
    bad = [t.get("flagged") or "it failed" for t in tasks if t.get("status") == "failed"]
    bad += [f"{x.get('step')}: {x.get('note') or 'it failed'}" for x in st.get("steps") or []
            if x.get("status") == "failed" and x.get("task") is None]
    return f"failed: {bad[0].splitlines()[0]}" if bad else "finished"


def message(ctx) -> str:
    """The one-line message: '<project>: <title> <outcome>: N passed, M failed, K skipped. Summary: <path>'."""
    st = state.load(ctx.run.folder)
    spec = atomic.read_json(ctx.run.folder / "spec.json") or ctx.run.spec or {}
    passed, failed, skipped = _counts(st.get("tasks") or {})
    outcome = _outcome(st)
    verb = outcome if outcome in ("finished", "stopped") else "failed"
    text = f"{ctx.project.name}: {spec.get('title') or ctx.run.id} {verb}: {passed} passed, {failed} failed, {skipped} skipped"
    if verb == "failed":
        text += f" ({outcome[len('failed: '):]})"
    path = ctx.run.folder / "summary.md"
    return text + (f". Summary: {path}" if path.exists() else ".")


def run(ctx):
    """Send the message through the notify adapter."""
    ctx.adapters.notify.send(scrub.scrub(message(ctx)))
    return StepResult("pass")
