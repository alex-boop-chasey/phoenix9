"""Commit: records the task's change on the run's branch."""
from phoenix9 import atomic, git
from phoenix9.stepctx import StepResult

AUTHOR = "Phoenix 9 <phoenix@localhost>"


def run(ctx):
    """Commit the worktree (no env files, never empty) with Phoenix-Run/Task/Attempt trailers."""
    task = ctx.task
    n = task["number"]
    try:
        sha = ctx.adapters.git.commit(
            ctx.worktree, f"Task {n}: {task['title']}",
            {"Phoenix-Run": ctx.run.id, "Phoenix-Task": str(n), "Phoenix-Attempt": str(ctx.attempt)},
            skip_env=True, allow_empty=False, author=AUTHOR)
    except git.GitError as e:
        if "Nothing to commit" in str(e):
            return StepResult("fail", ["Nothing to commit"])
        raise
    path = ctx.run.folder / "progress.md"
    old = path.read_text() if path.exists() else ""
    atomic.write_text(path, old + f"Task {n} passed on attempt {ctx.attempt}: {sha[:12]} {task['title']}\n")
    return StepResult("pass", produces={"commit": sha})
