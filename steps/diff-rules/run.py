"""Diff rules: fails the task if the builder touched files it may not."""
from phoenix9 import atomic, checklock, state
from phoenix9.stepctx import StepResult


def _reason(line: str) -> str:
    """Turn 'M .env: why' into 'Not allowed to change .env (why)'."""
    head, _, why = line.rpartition(": ")
    where = head.split(" ", 1)[1] if " " in head else head
    return f"Not allowed to change {where} ({why})"


def run(ctx):
    """Check the attempt's changes (since attempt_base) and the locked checks against the rules."""
    git, n = ctx.adapters.git, ctx.task["number"]
    base = state.load(ctx.run.folder)["tasks"][str(n)].get("attempt_base") or git.head(ctx.worktree)
    diff = ctx.project.settings.get("diff") or {}
    changes = git.diff_changes(ctx.worktree, base)
    bad = [_reason(r) for r in git.check_changes(
        changes,
        allow_extra=[*ctx.project.profile.get("diff_allow_extra", ()), *diff.get("allow_extra", ())],
        deny_extra=list(diff.get("deny_extra", ())),
        locked=checklock.locked_paths(ctx.run.folder))]
    bad += [p for p in checklock.verify(ctx.run.folder, n, ctx.worktree) if p not in bad]
    folder = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}"
    lines = bad or [f"allowed: {c.path}" for c in changes] or ["no changes"]
    atomic.write_text(folder / "diff-rules.txt", "\n".join(lines) + "\n")
    return StepResult("fail", bad) if bad else StepResult("pass")
