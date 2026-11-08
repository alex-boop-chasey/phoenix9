"""The repair note steps: one function per step, and the registry the apply engine looks them up in."""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from phoenix9 import failmodes, git, scrub, state
from phoenix9.repair import snapshot


class StepRefused(Exception):
    """A step cannot be done; the message says why in plain words."""


@dataclass
class Context:
    """What a step is given: the run folder to change (a scratch copy in a dry run) and how it was asked."""
    run_dir: object
    dry: bool = False
    approve_unlock: bool = False


def _task(ctx, n: int) -> dict:
    """The state entry of task n, or refuse when the run has no such task."""
    task = (state.load(ctx.run_dir).get("tasks") or {}).get(str(n))
    if task is None:
        raise StepRefused(f"task {n} is not in this run")
    return task


def _unwaiting(ctx, n: int) -> None:
    """Refuse when task n waits on an open question (close the question first)."""
    if _task(ctx, n).get("gate"):
        raise StepRefused(f"task {n} is waiting on a question; close the question first")


def _skip_dependents(st: dict, n: int, why: str) -> list[int]:
    """Skip every unfinished task that needs task n, directly or through others; return their numbers."""
    tasks, skipped, todo = st["tasks"], [], [str(n)]
    while todo:
        cur = todo.pop()
        for key, t in sorted(tasks.items(), key=lambda kv: int(kv[0])):
            if cur in [str(d) for d in t.get("depends_on") or []] and key not in todo and int(key) not in skipped:
                if t.get("status") in ("pending", "running", "waiting"):
                    t.update(status="skipped", gate=None, note=why)
                    skipped.append(int(key))
                todo.append(key)
    return sorted(skipped)


def mark_done(ctx, n: int, why: str) -> str:
    """Mark task n passed, with the reason as its note and its flag cleared."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(
        status="passed", note=scrub.scrub(why), flagged="", gate=None, rerun=False))
    return f"task {n} is now done ({scrub.scrub(why)})"


def mark_skipped(ctx, n: int, why: str) -> str:
    """Mark task n skipped, and skip the unfinished tasks that depend on it."""
    _unwaiting(ctx, n)
    skipped = []

    def change(s):
        s["tasks"][str(n)].update(status="skipped", note=scrub.scrub(why), gate=None, rerun=False)
        skipped.extend(_skip_dependents(s, n, f"depends on task {n}, which was skipped"))
    state.update(ctx.run_dir, change)
    more = f"; also skipped task {', '.join(map(str, skipped))}" if skipped else ""
    return f"task {n} is now skipped ({scrub.scrub(why)}){more}"


def retry(ctx, n: int) -> str:
    """Put task n back to pending with rerun on, keeping its failures."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(status="pending", rerun=True, flagged=""))
    return f"task {n} will run again (its earlier failures are kept)"


def clear_failures(ctx, n: int) -> str:
    """Forget the failure reasons of task n."""
    count = len(_task(ctx, n).get("failures") or [])
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(failures=[]))
    return f"cleared {count} failure(s) of task {n}"


def add_note(ctx, n: int, text: str) -> str:
    """Add a note to the failures of task n, which the next attempt reads."""
    line = "Note from the repair: " + scrub.scrub(text)
    _task(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].setdefault("failures", []).append(line))
    return f"added a note to task {n}"


# ---------------------------------------------------------------------- worktree steps
QUIET = SimpleNamespace(notify=SimpleNamespace(send=lambda text: None), git=git)


def _work(ctx) -> Path:
    """The run's worktree, or refuse when it is gone (rebuild the worktree is the step for that)."""
    work = snapshot.worktree_of(ctx.run_dir)
    if not work.is_dir():
        raise StepRefused("the worktree is gone; use 'rebuild the worktree' first")
    return work


def _snapshot_number(ctx) -> int:
    """The number of the snapshot taken for this repair (the newest one)."""
    return max(snapshot._numbers(Path(ctx.run_dir)), default=1)


def _hard_reset(work: Path, sha: str) -> None:
    """Reset the worktree hard to sha and drop untracked files, but keep env files (undo cannot bring them back)."""
    git.git(work, "reset", "-q", "--hard", sha)
    git.git(work, "clean", "-fdq", "-e", ".env*")


def _env_task(ctx) -> int | None:
    """The task env files are filed under: the current task, else the first failed one, else the first."""
    st = state.load(ctx.run_dir)
    tasks = st.get("tasks") or {}
    current = (st.get("current") or {}).get("task")
    if current is not None and str(current) in tasks:
        return int(current)
    failed = sorted(int(k) for k, t in tasks.items() if t.get("status") == "failed")
    return failed[0] if failed else min(map(int, tasks), default=None)


def _moved_text(moved: list[str], task: int) -> str:
    """Plain words for the env files moved out of the worktree."""
    return f"; moved env file(s) {', '.join(moved)} to tasks/{task}/outside-env/" if moved else ""


def redo(ctx, n: int) -> str:
    """Put task n and every later task back to pending (tries 0, failures cleared), move their attempts aside
    and reset the worktree to the commit task n started from."""
    tasks = (state.load(ctx.run_dir).get("tasks") or {})
    _task(ctx, n)
    later = sorted(int(k) for k in tasks if int(k) >= n)
    for k in later:
        _unwaiting(ctx, k)
    base = tasks[str(n)].get("attempt_base")
    if not base:
        raise StepRefused(f"task {n} has no recorded start commit, so its work cannot be reset")
    work = None if ctx.dry else _work(ctx)
    keep = ("title", "depends_on", "escalations")

    def change(s):
        for k in later:
            t = s["tasks"][str(k)]
            fresh = state.new_task()
            fresh.update({f: t[f] for f in keep if f in t})
            if k == n:
                fresh["attempt_base"] = base
            t.clear()
            t.update(fresh)
        s["steps"] = [x for x in s["steps"] if x.get("task") is None or x["task"] < n]
        if (s.get("current") or {}).get("task") in later:
            s["current"].update(task=None, step=None, attempt=None, gate=None)
    state.update(ctx.run_dir, change)
    number = _snapshot_number(ctx)
    for k in later:
        for folder in sorted((Path(ctx.run_dir) / "tasks" / str(k)).glob("attempt-*")):
            snapshot.move_to_removed(ctx.run_dir, number, folder)
    if work is not None:
        _hard_reset(work, base)
    names = ", ".join(map(str, later))
    return f"task {names} will start again from scratch" + ("" if work else " (the worktree is not touched in a dry run)")


def keep_hand_fix(ctx, message: str) -> str:
    """Commit the uncommitted worktree changes as an outside fix and start the current task from that commit."""
    task = _env_task(ctx)
    if task is None:
        raise StepRefused("this run has no tasks")
    if ctx.dry:
        return f"would commit the hand fix with message \"{scrub.scrub(message)}\""
    work = _work(ctx)
    moved = failmodes.move_env_out(QUIET, ctx.run_dir, work, task)
    extra = _moved_text(moved, task)
    if not git.pending_paths(work, skip_env=True):
        return "the worktree has no changes to keep" + extra
    if git.scan_secrets(git.diff_text(work, "HEAD")):
        raise StepRefused("the worktree changes look like they hold a secret; take it out first")
    run_id = state.load(ctx.run_dir)["run_id"]
    sha = git.commit(work, scrub.scrub(message), {"Phoenix-Run": run_id, "Phoenix-Task": str(task),
                                                  "Phoenix-Fix-By": "repair"}, skip_env=True)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(task)].update(attempt_base=sha))
    return f"committed the hand fix as {sha[:10]}; task {task} now starts from it{extra}"


def _on_branch_or_main(work: Path, run_id: str, sha: str) -> bool:
    """True when the commit is part of phoenix/<run> or of main."""
    for ref in (git.branch_name(run_id), git.MAIN):
        if git.run_git(work, "merge-base", "--is-ancestor", sha, f"refs/heads/{ref}", check=False).returncode == 0:
            return True
    return False


def _lost_bases(ctx, work: Path) -> list[int]:
    """Tasks whose attempt_base the worktree no longer contains."""
    lost = []
    for k, t in sorted((state.load(ctx.run_dir).get("tasks") or {}).items(), key=lambda kv: int(kv[0])):
        base = t.get("attempt_base")
        if base and git.run_git(work, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode != 0:
            lost.append(int(k))
    return lost


def reset_worktree(ctx, sha: str) -> str:
    """Reset the worktree to a commit of phoenix/<run> or main; name the tasks whose start commit is then gone."""
    work = _work(ctx)
    found = git.run_git(work, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}", check=False)
    if found.returncode != 0:
        raise StepRefused(f"{sha} is not a commit of this project")
    full = found.stdout.decode().strip()
    if not _on_branch_or_main(work, Path(ctx.run_dir).name, full):
        raise StepRefused(f"{sha} is not a commit on {git.branch_name(Path(ctx.run_dir).name)} or main")
    if ctx.dry:
        return f"would reset the worktree to {full[:10]}"
    _hard_reset(work, full)
    lost = _lost_bases(ctx, work)
    tail = (f"; task {', '.join(map(str, lost))} no longer has its start commit (redo it, or the check fails)"
            if lost else "")
    return f"reset the worktree to {full[:10]}{tail}"


def rebuild_worktree(ctx) -> str:
    """Remove the worktree and make it again from the branch; uncommitted and untracked files are dropped."""
    run_dir = Path(ctx.run_dir)
    if ctx.dry:
        return "would rebuild the worktree from its branch"
    work, code = snapshot.worktree_of(run_dir), snapshot.code_dir_of(run_dir)
    moved, task = [], _env_task(ctx)
    if work.is_dir() and task is not None:
        moved = failmodes.move_env_out(QUIET, run_dir, work, task)
    try:
        git.remove_worktree(code, work)
        git.make_worktree(code, run_dir.name, work)
    except git.GitError as e:
        raise StepRefused(f"the worktree could not be rebuilt: {scrub.scrub(str(e))}") from e
    return "rebuilt the worktree from its branch (uncommitted and untracked files were dropped)" + (
        _moved_text(moved, task) if moved else "")


STEPS = {"redo": redo, "keep-hand-fix": keep_hand_fix, "reset-worktree": reset_worktree,
         "rebuild-worktree": rebuild_worktree, "mark-done": mark_done, "mark-skipped": mark_skipped, "retry": retry,
         "clear-failures": clear_failures, "add-note": add_note}


def run_step(ctx, step) -> str:
    """Do one parsed step; refuse the ones that are not built yet. Returns what it changed, in words."""
    fn = STEPS.get(step.kind)
    if fn is None:
        raise StepRefused(f"'{step.text}' is not supported yet")
    return fn(ctx, **step.args)
