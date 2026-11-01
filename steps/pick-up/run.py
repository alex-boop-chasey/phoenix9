"""Pick-up: checks the run's spec copy is there and says the run has started."""
from phoenix9.stepctx import StepResult


def run(ctx):
    """Fail when the run has no spec.md; otherwise emit run.started."""
    spec = ctx.run.folder / "spec.md"
    if not spec.is_file():
        return StepResult("fail", ["The run has no spec copy (spec.md)."])
    ctx.emit("run.started")
    return StepResult("pass")
