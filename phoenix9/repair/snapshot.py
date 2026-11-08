"""Snapshots for the repair kit: a copy of a run's state and worktree changes taken before any repair."""
import json
import re
import shutil
import time
from pathlib import Path

from phoenix9 import atomic, events, git, heartbeat, paths, runend, scrub, state

TOP_FILES = ("state.json", "settings.json", "plan.json", "things.json", "spec.json", "spec.md", "overrides.json")
FROZEN = "repairs/frozen.json"
NEVER_READ = ("secrets", "keys")


class SnapshotError(Exception):
    """A snapshot could not be taken; the message says why in plain words."""


def repairs_dir(run_dir: Path) -> Path:
    """Return the folder that holds a run's repairs."""
    return Path(run_dir) / "repairs"


def _numbers(run_dir: Path) -> list[int]:
    """List the repair numbers already used in a run."""
    base = repairs_dir(run_dir)
    if not base.is_dir():
        return []
    return sorted(int(p.name) for p in base.iterdir() if re.fullmatch(r"[0-9]+", p.name) and p.is_dir())


def next_number(run_dir: Path) -> int:
    """Return the number the next repair of this run gets (1, 2, 3 ...)."""
    nums = _numbers(run_dir)
    return nums[-1] + 1 if nums else 1


def worktree_of(run_dir: Path) -> Path:
    """Return the git worktree that belongs to a run folder (HOME/runs/<project>/<run>)."""
    run_dir = Path(run_dir)
    return paths.work(run_dir.parent.name, run_dir.name)


def _copyable(path: Path) -> bool:
    """True for a plain file that is not an env file and not under secrets/ or keys/."""
    if path.is_symlink() or not path.is_file() or git.is_env_file(path.name):
        return False
    return not any(part in NEVER_READ for part in path.parts)


def _files_to_copy(run_dir: Path) -> list[Path]:
    """List the run files a snapshot keeps, as paths relative to the run folder."""
    found = [Path(name) for name in TOP_FILES + (FROZEN,) if _copyable(run_dir / name)]
    gates = run_dir / "gates"
    if gates.is_dir():
        found += sorted(p.relative_to(run_dir) for p in gates.rglob("*") if _copyable(p))
    found += sorted(p.relative_to(run_dir) for p in run_dir.glob("tasks/*/attempt-*/result.json") if _copyable(p))
    return found


def _attempt_folders(run_dir: Path) -> list[str]:
    """List the attempt folders of a run (tasks/<n>/attempt-<k>), relative to the run folder."""
    return sorted(p.relative_to(run_dir).as_posix() for p in Path(run_dir).glob("tasks/*/attempt-*") if p.is_dir())


def _non_env(names: list[str]) -> list[str]:
    """Drop .env-style files from a list of paths."""
    return [n for n in names if not git.is_env_file(n.rsplit("/", 1)[-1])]


def _names(work: Path, *args: str) -> list[str]:
    """Run a git command that lists paths with -z and return them."""
    return [n for n in git.git(work, *args).split("\0") if n]


def _patch_text(work: Path) -> str:
    """Return the changes of tracked and untracked files against HEAD as one patch, env files left out."""
    tracked = _non_env(_names(work, "diff", "--name-only", "-z", "HEAD"))
    text = git.git(work, "diff", "--binary", "HEAD", "--", *tracked) if tracked else ""
    for name in _non_env(_names(work, "ls-files", "--others", "--exclude-standard", "-z")):
        one = git.run_git(work, "diff", "--no-index", "--binary", "--", "/dev/null", name, check=False)
        text += one.stdout.decode(errors="replace")
    return text


def _worktree_info(work: Path) -> dict:
    """Return head, branch and whether the worktree has uncommitted changes."""
    return {"head": git.head(work),
            "branch": git.git(work, "rev-parse", "--abbrev-ref", "HEAD").strip(),
            "dirty": bool(git.pending_paths(work, skip_env=True))}


def _safe_patch(work: Path) -> str:
    """Build the scrubbed patch; refuse (without writing anything) when it holds a secret."""
    patch = _patch_text(work)
    if git.scan_secrets(patch):
        raise SnapshotError("Snapshot refused: the worktree changes look like they hold a secret "
                            "(a key, token or password). Take it out of the worktree first.")
    return scrub.scrub(patch)


def code_dir_of(run_dir: Path) -> Path:
    """Return the project's own code repo (PHOENIX_PROJECTS/<project>/code), a place Phoenix wrote itself."""
    return paths.projects() / Path(run_dir).parent.name / "code"


def _missing_info(run_dir: Path) -> dict:
    """The worktree record for a missing or unreadable worktree: the branch tip read from the project's code repo."""
    branch = git.branch_name(Path(run_dir).name)
    try:
        tip = git.git(code_dir_of(run_dir), "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}").strip()
    except git.GitError as e:
        raise SnapshotError(f"Snapshot failed: the worktree is unreadable and branch {branch} cannot be read "
                            f"({scrub.scrub(str(e))}).") from e
    return {"head": tip, "branch": branch, "dirty": False, "missing": True}


def _read_worktree(run_dir: Path) -> tuple[dict, str]:
    """Return the worktree record and its patch; a missing or unreadable worktree is recorded as such."""
    work = worktree_of(run_dir)
    if not work.is_dir():
        return _missing_info(run_dir), ""
    try:
        return _worktree_info(work), _safe_patch(work)
    except git.GitError as e:
        try:
            return _missing_info(run_dir), ""
        except SnapshotError:
            raise SnapshotError(f"Snapshot failed: git could not read the worktree "
                                f"({scrub.scrub(str(e))}).") from e


def take(run_dir, label: str) -> int:
    """Copy the run's state files and worktree changes into repairs/<n>/before/ and return n."""
    run_dir = Path(run_dir)
    info, patch = _read_worktree(run_dir)
    n = next_number(run_dir)
    tmp = repairs_dir(run_dir) / f".tmp-{n}"
    final = repairs_dir(run_dir) / str(n)
    shutil.rmtree(tmp, ignore_errors=True)
    before = tmp / "before"
    try:
        before.mkdir(parents=True)
        for rel in _files_to_copy(run_dir):
            (before / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run_dir / rel, before / rel)
        atomic.write_text(before / "label.txt", f"{label}\n")
        atomic.write_text(before / "worktree.json", json.dumps(info, indent=2) + "\n")
        atomic.write_text(before / "worktree.patch", patch)
        atomic.write_text(before / "attempts.json", json.dumps(_attempt_folders(run_dir)) + "\n")
        tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return n


def move_to_removed(run_dir, n: int, path) -> Path:
    """Move a folder of the run (an attempt) into repairs/<n>/removed/<same relative path>; return the new place."""
    run_dir = Path(run_dir)
    src = Path(path)
    if not src.is_absolute():
        src = run_dir / src
    try:
        rel = src.resolve().relative_to(run_dir.resolve())
    except ValueError as e:
        raise SnapshotError("Only folders inside the run folder can be moved aside.") from e
    dest = repairs_dir(run_dir) / str(n) / "removed" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest


class RepairRefused(Exception):
    """A repair was refused; the message says why in plain words."""


WALKING_MESSAGE = "The runner is walking this run. Stop it first or wait for a question."
LOCK_WAIT_S = 3.0


def refuse_if_walking(run_dir, lock_ok: bool = False) -> None:
    """Refuse (RepairRefused) when the runner is walking the run: running with a fresh heartbeat, or the run lock
    busy (lock_ok: the caller holds that lock itself, so only the state and heartbeat are looked at)."""
    run_dir = Path(run_dir)
    if not lock_ok and state.Lock.held(run_dir / "run.lock"):
        raise RepairRefused(WALKING_MESSAGE)
    st = state.load(run_dir) or {}
    if st.get("status") == "running" and not heartbeat.is_stale(time.time()):
        raise RepairRefused(WALKING_MESSAGE)


def label_of(run_dir, n: int) -> str:
    """Return the label text of snapshot n."""
    try:
        return (repairs_dir(run_dir) / str(n) / "before" / "label.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _snapshot_before(run_dir: Path, n: int) -> Path:
    """Return the before/ folder of snapshot n, or refuse when there is no such snapshot."""
    before = repairs_dir(run_dir) / str(n) / "before"
    if not (before / "worktree.json").is_file():
        raise RepairRefused(f"There is no repair snapshot number {n} for this run.")
    return before


def _in_scope(rel: str) -> bool:
    """True for run files a snapshot owns: the top files, gates/ and attempt result.json files."""
    parts = rel.split("/")
    return rel in TOP_FILES or rel == FROZEN or parts[0] == "gates" or (
        len(parts) == 4 and parts[0] == "tasks" and parts[2].startswith("attempt-") and parts[3] == "result.json")


def _kept_files(before: Path) -> list[str]:
    """List the run files kept in a snapshot, relative paths."""
    skip = ("label.txt", "worktree.json", "worktree.patch", "attempts.json")
    return sorted(p.relative_to(before).as_posix() for p in before.rglob("*") if p.is_file()
                  and p.relative_to(before).as_posix() not in skip)


def _attempts_at(before: Path, kept: list[str]) -> set[str]:
    """The attempt folders that existed when snapshot `before` was taken."""
    listing = atomic.read_json(before / "attempts.json")
    if isinstance(listing, list):
        return set(listing)
    return {k.rsplit("/", 1)[0] for k in kept if k.endswith("/result.json") and k.startswith("tasks/")}


def _move_aside_new_attempts(run_dir: Path, m: int, existed: set[str]) -> None:
    """Move attempt folders that did not exist at the snapshot into repairs/<m>/removed/."""
    for folder in sorted(run_dir.glob("tasks/*/attempt-*")):
        if folder.is_dir() and folder.relative_to(run_dir).as_posix() not in existed:
            move_to_removed(run_dir, m, folder)


def _restore_removed(run_dir: Path, n: int, last: int, existed: set[str]) -> None:
    """Move attempt folders back from repairs/<n..last>/removed/ when they existed at snapshot n and are gone now."""
    for k in range(n, last + 1):
        removed = repairs_dir(run_dir) / str(k) / "removed"
        for folder in sorted(removed.glob("tasks/*/attempt-*")) if removed.is_dir() else []:
            rel = folder.relative_to(removed)
            dest = run_dir / rel
            if folder.is_dir() and rel.as_posix() in existed and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(folder), str(dest))


def _restore_files(run_dir: Path, before: Path) -> None:
    """Put the kept run files back byte for byte and delete in-scope files made after the snapshot."""
    kept = _kept_files(before)
    for rel in kept:
        target = run_dir / rel
        if rel == "state.json":
            with state.Lock(run_dir / "state.lock"):
                shutil.copyfile(before / rel, run_dir / ".state.json.restore")
                (run_dir / ".state.json.restore").replace(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.restore")
        shutil.copyfile(before / rel, tmp)
        shutil.copymode(target, tmp) if target.exists() else None
        tmp.replace(target)             # replaced, not written into: spec.md is read-only
    now_there = [name for name in TOP_FILES + (FROZEN,) if (run_dir / name).is_file()]
    now_there += [p.relative_to(run_dir).as_posix() for p in (run_dir / "gates").rglob("*") if p.is_file()] \
        if (run_dir / "gates").is_dir() else []
    now_there += [p.relative_to(run_dir).as_posix() for p in run_dir.glob("tasks/*/attempt-*/result.json")]
    for rel in now_there:
        if _in_scope(rel) and rel not in kept and _copyable(run_dir / rel):
            (run_dir / rel).unlink()


def _ensure_worktree(run_dir: Path, work: Path) -> None:
    """Recreate the worktree from its branch when it is missing or git cannot read it."""
    if work.is_dir():
        top = git.run_git(work, "rev-parse", "--show-toplevel", check=False)
        if top.returncode == 0 and Path(top.stdout.decode().strip()).resolve() == work.resolve():
            return
    code = code_dir_of(run_dir)
    git.remove_worktree(code, work)
    git.make_worktree(code, run_dir.name, work)


def _restore_worktree(run_dir: Path, before: Path) -> None:
    """Reset the worktree hard to the snapshot's head on its branch and re-apply the dirty patch."""
    work = worktree_of(run_dir)
    info = json.loads((before / "worktree.json").read_text(encoding="utf-8"))
    try:
        _ensure_worktree(run_dir, work)
        if git.git(work, "rev-parse", "--abbrev-ref", "HEAD").strip() != info["branch"]:
            git.git(work, "checkout", "-q", info["branch"])
        git.git(work, "reset", "--hard", "-q", info["head"])
        git.git(work, "clean", "-fdq", "-e", ".env*")
        patch = (before / "worktree.patch").read_bytes()
        if info.get("dirty") and patch.strip():
            git.run_git(work, "apply", "--binary", "--whitespace=nowarn", "-", input=patch)
    except git.GitError as e:
        raise RepairRefused(f"Undo failed: git could not restore the worktree ({scrub.scrub(str(e))}).") from e


def _find_run_project(run_dir: Path) -> str:
    """The project name of a run folder."""
    return run_dir.parent.name


def _record(run_dir: Path, who: str, n: int, m: int) -> None:
    """Write the repair.applied event, the commands-log line and the changelog line for an undo."""
    from phoenix9.ops import common
    project, run = _find_run_project(run_dir), run_dir.name
    title = f"undo to {n}"
    events.emit("repair.applied", project=project, run=run, who=who, note=None, title=title,
                steps=[f"restore snapshot {n}"], check_before=None, check_after=None, forced=False,
                rolled_back=False, snapshot=m)
    common.record_command(who, f"repair undo {run} --to {n}", project,
                          f"repair on run {run}: undid back to snapshot {n} (new snapshot {m})")


def _restore(run_dir: Path, n: int, aside: int, last: int) -> None:
    """Put the run back as snapshot n had it; new attempts go aside into repairs/<aside>/removed/."""
    before = _snapshot_before(run_dir, n)
    existed = _attempts_at(before, _kept_files(before))
    _move_aside_new_attempts(run_dir, aside, existed)
    _restore_removed(run_dir, n, last, existed)
    _restore_files(run_dir, before)
    _restore_worktree(run_dir, before)


def roll_back(run_dir, n: int) -> None:
    """Put the run back as snapshot n had it (the caller holds the run lock); used when a repair fails."""
    _restore(Path(run_dir), n, n, n)


def undo(run_dir, to: int | None = None, who: str = "cli") -> dict:
    """Restore snapshot `to` (default the newest) exactly, after taking an 'undo to <n>' snapshot of its own."""
    run_dir = Path(run_dir)
    refuse_if_walking(run_dir)
    try:
        lock = runend.lock(run_dir, wait=LOCK_WAIT_S)
        lock.__enter__()
    except TimeoutError:
        raise RepairRefused(WALKING_MESSAGE) from None
    try:
        refuse_if_walking(run_dir, lock_ok=True)
        nums = _numbers(run_dir)
        n = nums[-1] if to is None and nums else to
        if n is None:
            raise RepairRefused("There is nothing to undo: this run has no repair snapshots.")
        _snapshot_before(run_dir, n)
        m = take(run_dir, f"undo to {n}")
        _restore(run_dir, n, m, m - 1)
    finally:
        lock.__exit__(None, None, None)
    _record(run_dir, who, n, m)
    return {"restored": n, "snapshot": m, "title": f"undo to {n}"}

