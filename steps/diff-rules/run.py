"""Diff rules: fails the task if the builder touched files it may not."""
from phoenix9.stepctx import StepResult


def run(ctx):
    """Check the worktree's changes since the last commit against the allow/deny rules."""
    changes = ctx.adapters.git.diff_changes(ctx.worktree, "HEAD")
    bad = ctx.adapters.git.check_changes(
        changes, allow_extra=ctx.project.profile.get("diff_allow_extra", ()),
        deny_extra=ctx.project.settings.get("diff_deny_extra", ()))
    return StepResult("fail", bad) if bad else StepResult("pass")
