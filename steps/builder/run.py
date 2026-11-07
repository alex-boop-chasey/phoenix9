"""Builder: Claude writes the code for one task; Phoenix judges only the files it left behind."""
from pathlib import Path

from phoenix9 import atomic, checklock, state
from phoenix9.aistep import finish_line, profile_test, task_text
from phoenix9.reports import NO_SERVICES_TEXT
from phoenix9.stepctx import StepResult

EARLY_END = ("crashed", "timed_out", "no_output", "error")
GIT_LOG_LINES = 200


def _done_when(task: dict | None) -> str:
    """The task's Done-when bullets as a numbered list."""
    items = (task or {}).get("done_when", [])
    return "\n".join(f"{i}. {c['text']}" for i, c in enumerate(items, 1)) or "(none)"


def _checks(ctx) -> str:
    """The locked check files, or (no Check-writer) the Done-when commands of the task."""
    checks = ctx.things.get("checks")
    if isinstance(checks, list) and checks:
        return "\n".join(f"- `{c}`" for c in checks)
    commands = [c["command"] for c in (ctx.task or {}).get("done_when", []) if c.get("command")]
    if commands:
        return "\n".join(f"- `{c}`" for c in commands)
    return "(no automatic checks; the Done-when list above is what counts)"


def _check_command(ctx, test: dict) -> str:
    """The command that runs this task's checks."""
    checks = ctx.things.get("checks")
    if isinstance(checks, list) and checks and test.get("check_command"):
        return test["check_command"].replace("{files}", " ".join(str(c) for c in checks))
    commands = [c["command"] for c in (ctx.task or {}).get("done_when", []) if c.get("command")]
    return "\n".join(commands) or test.get("task_cmd") or test.get("cmd", "")


def _git_log(ctx) -> str:
    """`git log --oneline` of the run's branch since it left the default branch (newest first, capped)."""
    git = ctx.adapters.git
    try:
        base = git.git(ctx.worktree, "merge-base", git.default_branch(ctx.project.code_dir), "HEAD").strip()
        lines = git.git(ctx.worktree, "log", "--oneline", f"{base}..HEAD").splitlines()
    except Exception:
        return "(no commits yet)"
    if len(lines) > GIT_LOG_LINES:
        lines = lines[:GIT_LOG_LINES] + [f"... and {len(lines) - GIT_LOG_LINES} older commits"]
    return "\n".join(lines) or "(no commits yet)"


def _failures(ctx) -> str:
    """Earlier attempts' reasons as a numbered list."""
    items = list(ctx.things.get("failures") or [])
    return "\n".join(f"{i}. {r}" for i, r in enumerate(items, 1)) or "None: this is the first try"


def _services(ctx) -> str:
    """The service notes: the text of services.md when Service setup wrote it, else the fallback text."""
    notes = str(ctx.things.get("service-notes") or "")
    path = Path(notes) if notes and len(notes) < 1000 else None
    if path is not None and path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return notes if notes and notes != "no-services" else NO_SERVICES_TEXT


def before(ctx) -> dict:
    """Fill the builder prompt's placeholders."""
    test = profile_test(ctx)
    return {
        "spec_title": ctx.run.spec.get("title", ""),
        "task": task_text(ctx.task),
        "about": ctx.run.spec.get("about", "").strip() or "(none)",
        "done_when": _done_when(ctx.task),
        "checks": _checks(ctx),
        "checks_dir": checklock.run_checks_dir(test, ctx.run.id),
        "check_command": _check_command(ctx, test),
        "suite_command": test.get("cmd", ""),
        "git_log": _git_log(ctx),
        "services": _services(ctx),
        "failures": _failures(ctx),
        "attempt": ctx.attempt,
        "max_tries": ctx.project.settings.get("max_tries", 1),
    }


def after(ctx, session) -> StepResult:
    """Judge the session from its files: write diff.patch; the builder's own words never pass a task."""
    if session.kind in EARLY_END:
        return StepResult("fail", [f"The builder session ended before it finished ({session.kind}). "
                                   f"End of its output:\n{(session.text or '')[-1000:]}"])
    kind, detail = finish_line(session.text)
    if kind == "spec_problem":
        return StepResult("fail", [f"SPEC_PROBLEM: {detail}"])
    n = ctx.task["number"]
    base = state.load(ctx.run.folder)["tasks"][str(n)].get("attempt_base") or ctx.adapters.git.head(ctx.worktree)
    patch = ctx.adapters.git.diff_text(ctx.worktree, base, binary=True)
    if not patch.strip():
        why = "The builder changed no files"
        return StepResult("fail", [f"{why}. It said: {detail}" if kind == "blocked" else why])
    out = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}" / "diff.patch"
    atomic.write_text(out, patch)
    return StepResult("pass", produces={"diff": str(out)})
