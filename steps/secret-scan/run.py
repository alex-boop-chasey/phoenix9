"""Secret scan: fails the task if the change adds something that looks like a key or password."""
from phoenix9.stepctx import StepResult


def run(ctx):
    """Scan the lines added since the last commit."""
    found = ctx.adapters.git.scan_secrets(ctx.adapters.git.diff_text(ctx.worktree, "HEAD"))
    return StepResult("fail", found) if found else StepResult("pass")
