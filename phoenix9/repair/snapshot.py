"""Snapshots for the repair kit: a copy of a run's state and worktree changes taken before any repair."""
import json
import re
import shutil
from pathlib import Path

from phoenix9 import atomic, git, paths, scrub

TOP_FILES = ("state.json", "settings.json", "plan.json", "things.json", "spec.json", "spec.md", "overrides.json")
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
    found = [Path(name) for name in TOP_FILES if _copyable(run_dir / name)]
    gates = run_dir / "gates"
    if gates.is_dir():
        found += sorted(p.relative_to(run_dir) for p in gates.rglob("*") if _copyable(p))
    found += sorted(p.relative_to(run_dir) for p in run_dir.glob("tasks/*/attempt-*/result.json") if _copyable(p))
    return found


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


def take(run_dir, label: str) -> int:
    """Copy the run's state files and worktree changes into repairs/<n>/before/ and return n."""
    run_dir = Path(run_dir)
    work = worktree_of(run_dir)
    if not work.is_dir():
        raise SnapshotError("Snapshot refused: the run's worktree is gone, so there is nothing to snapshot.")
    try:
        info, patch = _worktree_info(work), _safe_patch(work)
    except git.GitError as e:
        raise SnapshotError(f"Snapshot failed: git could not read the worktree ({scrub.scrub(str(e))}).") from e
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
