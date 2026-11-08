"""The run report: a plain-English view of a run, written from its real state, with a repair-note line per finding."""
from pathlib import Path

from phoenix9 import atomic, gates, git, scrub, state, status
from phoenix9.repair import check as check_mod
from phoenix9.repair.snapshot import repairs_dir, worktree_of

TAIL_LINES = 5


def report_path(run_dir) -> Path:
    """Where the report of a run lives."""
    return repairs_dir(Path(run_dir)) / "report.md"


def fix_line(f: check_mod.Finding) -> str:
    """The repair-note line that fixes one finding (the vocabulary of the repair note steps)."""
    kind, n = f.fix.get("kind"), f.task if f.task is not None else f.fix.get("task")
    lines = {
        "task-status": f"- set task {n} to failed",
        "step-line": f"- set step line {f.fix.get('line', 0)} to failed",
        "clear-gate": "- clear the waiting question of the run",
        "tries": f"- set tries of task {n} to {max(f.fix.get('folders') or [0])}",
        "attempt-result": f"- rewrite result of task {n} attempt {f.fix.get('attempt')}",
        "close-question": f"- close question {f.fix.get('gate')}",
        "run-status": "- set run to failed",
        "set-status": "- set run to failed",
        "worktree-branch": "- put the worktree on the run's branch",
        "attempt-base": f"- reset attempt base of task {n}",
        "env-file": f"- delete env file {f.fix.get('path')}",
        "worktree-missing": "- recreate the worktree",
        "plan": "- rebuild the plan from settings",
        "settings": "- rebuild settings from the project",
        "spec": "- rebuild the tasks from spec.json",
    }
    return lines.get(kind, f"- (no ready fix; look at: {f.text})")


def _tail(run_dir: Path, n: int, tries: int) -> list[str]:
    """The last lines of the newest checks.txt of task n, scrubbed."""
    base = run_dir / "tasks" / str(n)
    for k in sorted(check_mod._attempt_numbers(run_dir, n), reverse=True):
        path = base / f"attempt-{k}" / "checks.txt"
        if path.is_file():
            text = scrub.scrub(path.read_text(encoding="utf-8", errors="replace"))
            return text.splitlines()[-TAIL_LINES:]
    return []


def _task_lines(run_dir: Path, st: dict) -> list[str]:
    """Each task in one line, with the tail of its last checks beneath."""
    out = []
    for n, t in check_mod._tasks(st):
        why = scrub.scrub("; ".join([t["flagged"]] if t.get("flagged") else (t.get("failures") or [])[-3:]))
        out.append(f"- Task {n} ({t.get('title', '')}): {t['status']}, try {t.get('tries', 0)}"
                   + (f". Why it failed: {why}" if why and t["status"] != "passed" else ""))
        out += [f"      {line}" for line in _tail(run_dir, n, t.get("tries", 0))]
    return out or ["- (no tasks)"]


def _questions(run_dir: Path) -> list[str]:
    """The open questions: id, title, actions."""
    open_ones = [g for g in gates.run_gates(run_dir) if g["state"] == "open"]
    return [f"- {g['id']}: {scrub.scrub(g.get('title', ''))} (actions: {', '.join(g.get('actions') or [])})"
            for g in open_ones] or ["- No question is open."]


def _worktree(run_dir: Path) -> list[str]:
    """Branch, HEAD, dirty files and env files of the worktree."""
    work = worktree_of(run_dir)
    if not (work / ".git").exists():
        return [f"- The worktree is missing ({work})."]
    try:
        branch = git.run_git(work, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.decode().strip()
        dirty = [ln[3:] for ln in git.run_git(work, "status", "--porcelain", check=False).stdout.decode().splitlines()]
        env = [f.fix["path"] for f in check_mod._env_findings(work)]
        return [f"- Branch: {branch}", f"- HEAD: {git.head(work)}",
                f"- Changed files: {', '.join(dirty) if dirty else 'none'}",
                f"- Env files found: {', '.join(env) if env else 'none'}"]
    except git.GitError as err:
        return [f"- Git cannot read the worktree: {err}"]


def build(run_dir) -> str:
    """The report text for a run, worked out from its state now."""
    run_dir = Path(run_dir)
    st = state.load(run_dir) or {}
    open_ids = {g["id"] for g in gates.run_gates(run_dir) if g["state"] == "open"}
    view = status.run_view(st, open_ids) if st.get("status") in status.ACTIVE else None
    found = check_mod.run_checks(run_dir)
    cur = st.get("current") or {}
    now = view["now"] if view else f"Now: {st.get('status')}."
    parts = [f"# Run report: {st.get('run_id', run_dir.name)}", "",
             "## What the run is doing",
             f"- Status: {st.get('status')}", f"- {now}",
             f"- Current task {cur.get('task')}, step {cur.get('step')}", "",
             "## Tasks", *_task_lines(run_dir, st), "",
             "## Open question", *_questions(run_dir), "",
             "## Worktree", *_worktree(run_dir), "",
             "## What the check found",
             *([f"{i}. {f.text}" for i, f in enumerate(found, 1)] or ["No problems found."]), ""]
    if found:
        parts += ["## Repair note lines (copy what you need)", *dict.fromkeys(fix_line(f) for f in found), ""]
    parts += ["## Details", f"- Run folder: {run_dir}", f"- Worktree: {worktree_of(run_dir)}",
              *[f"- {f.code}: task {f.task}, fix {f.fix}" for f in found]]
    return scrub.scrub("\n".join(parts) + "\n")


def write(run_dir) -> str:
    """Write repairs/report.md afresh from the run state and return the text."""
    text = build(run_dir)
    atomic.write_text(report_path(run_dir), text)
    return text
