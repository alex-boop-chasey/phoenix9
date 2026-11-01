"""Notify: sends Alex one line about how the run ended."""
from phoenix9 import state
from phoenix9.stepctx import StepResult


def run(ctx):
    """Send a one-line message through the notify adapter."""
    tasks = state.load(ctx.run.folder)["tasks"]
    passed = sum(1 for t in tasks.values() if t["status"] == "passed")
    ctx.adapters.notify.send(f"Phoenix run {ctx.run.id} finished: {passed} of {len(tasks)} tasks passed.")
    return StepResult("pass")
