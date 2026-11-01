"""Commit: records the task's change on the run's branch."""
from phoenix9.stepctx import StepResult


def run(ctx):
    """Commit the worktree with Phoenix-Run and Phoenix-Task trailers."""
    task = ctx.task
    sha = ctx.adapters.git.commit(
        ctx.worktree, f"Task {task['number']}: {task['title']}",
        {"Phoenix-Run": ctx.run.id, "Phoenix-Task": str(task["number"])})
    return StepResult("pass", produces={"commit": sha})
