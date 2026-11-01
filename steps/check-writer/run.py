"""Check-writer: Claude writes the task's checks; Phoenix accepts only files in the task's checks folder, then locks them."""
import fnmatch
from pathlib import Path

from phoenix9 import checklock, state
from phoenix9.aistep import last_line, profile_test, task_text
from phoenix9.stepctx import StepResult

EARLY_END = ("crashed", "timed_out", "no_output", "error")
TREE_LINES = 400
EXISTING_CHECKS_CHARS = 20000


def _done_when(task: dict | None) -> str:
    """The task's Done-when bullets as a numbered list."""
    items = (task or {}).get("done_when", [])
    return "\n".join(f"{i}. {c['text']}" for i, c in enumerate(items, 1)) or "(none)"


# ported from reference/v8/phoenix/checks.py:198
def repo_tree(ctx) -> str:
    """`git ls-files` of the worktree, cut to a few hundred lines."""
    files = [f for f in ctx.adapters.git.git(ctx.worktree, "ls-files").splitlines() if f]
    if not files:
        return "(the repo has no files yet)"
    shown = files[:TREE_LINES]
    if len(files) > TREE_LINES:
        shown.append(f"... and {len(files) - TREE_LINES} more files")
    return "\n".join(shown)


# ported from reference/v8/phoenix/checks.py:209
def existing_checks(ctx, own_dir: str) -> str:
    """The locked checks of other tasks (path and contents), cut to about 20000 characters."""
    parts, size = [], 0
    for rel in checklock.locked_paths(ctx.run.folder):
        if rel.endswith("/") or rel.startswith(own_dir + "/"):
            continue
        try:
            text = (Path(ctx.worktree) / rel).read_text(errors="replace")
        except OSError:
            continue
        block = f"### {rel}\n```\n{text.rstrip()}\n```\n"
        if size + len(block) > EXISTING_CHECKS_CHARS:
            parts.append("(more checks left out to keep this prompt short)")
            break
        parts.append(block)
        size += len(block)
    return "\n".join(parts) or "(none yet)"


def before(ctx) -> dict:
    """Fill the check-writer prompt's placeholders."""
    test = profile_test(ctx)
    folder = checklock.task_checks_dir(test, ctx.task["number"])
    return {
        "spec_title": ctx.run.spec.get("title", ""),
        "task": task_text(ctx.task),
        "about": ctx.run.spec.get("about", "").strip() or "(none)",
        "done_when": _done_when(ctx.task),
        "checks_dir": folder,
        "check_files": test.get("check_files") or "*",
        "check_command": test.get("check_command", "").replace("{files}", f"{folder}/"),
        "repo_tree": repo_tree(ctx),
        "existing_checks": existing_checks(ctx, folder),
    }


def _wanted(path: str, folder: str, patterns: list[str]) -> bool:
    """True when the path is inside the checks folder and its name fits a check_files pattern."""
    if not path.startswith(folder + "/"):
        return False
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def after(ctx, session) -> StepResult:
    """Accept only new check files in the task's folder, commit and lock them."""
    if session.kind in EARLY_END:
        return StepResult("fail", [f"The check writer session ended before it finished ({session.kind}). "
                                   f"End of its output:\n{(session.text or '')[-1000:]}"])
    line = last_line(session.text).strip("`* ")
    if line.startswith("SPEC_PROBLEM:"):
        return StepResult("fail", [line])
    git, n = ctx.adapters.git, ctx.task["number"]
    test = profile_test(ctx)
    folder = checklock.task_checks_dir(test, n)
    patterns = (test.get("check_files") or "*").split()
    base = state.load(ctx.run.folder)["tasks"][str(n)].get("attempt_base") or git.head(ctx.worktree)
    changes = git.diff_changes(ctx.worktree, base)
    bad = [c.path for c in changes if c.status not in ("A", "M") or not _wanted(c.path, folder, patterns)]
    if bad:
        return StepResult("fail", [f"The check writer changed files other than new checks in {folder}/: "
                                   + ", ".join(sorted(bad))])
    written = sorted(c.path for c in changes)
    if not written:
        why = "The check writer wrote no checks"
        return StepResult("fail", [f"{why}. It said: {line}" if line.startswith("CHECKS BLOCKED") else why])
    git.commit(ctx.worktree, f"Checks for task {n}", {"Phoenix-Run": ctx.run.id, "Phoenix-Task": str(n)})
    checklock.lock(ctx.run.folder, n, ctx.worktree, written)
    return StepResult("pass", produces={"checks": written})
