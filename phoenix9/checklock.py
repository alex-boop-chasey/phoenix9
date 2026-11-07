"""Locks a task's check files by fingerprint; the manifest lives in the run folder, never in the repo."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path

from phoenix9 import atomic


def run_checks_dir(profile_test: dict, run_id: str) -> str:
    """The repo folder holding one run's checks: <checks_dir>/<run-id>.

    Per run, so checks an earlier build merged into main never sit in a later run's task folder."""
    if not run_id or run_id in (".", "..") or "/" in run_id or "\\" in run_id:
        raise ValueError(f"Not a usable run id for a checks folder: {run_id!r}")
    base = (profile_test.get("checks_dir") or "tests/phoenix").strip("/")
    return f"{base}/{run_id}"


def task_checks_dir(profile_test: dict, run_id: str, task_no: int) -> str:
    """The repo folder holding this task's checks: <checks_dir>/<run-id>/task-<n>."""
    return f"{run_checks_dir(profile_test, run_id)}/task-{task_no}"


SHELLS = ("sh", "bash", "dash", "zsh")


def check_commands(profile_test: dict, files: list[str]) -> list[str]:
    """The commands that run these check files: the profile's check_command with {files} filled in.

    A shell (`sh {files}`) runs only its first script and takes the other names as arguments, so a shell
    command gets one command per file; a test runner (pytest, vitest) gets all files in one command."""
    template = profile_test.get("check_command") or profile_test.get("cmd") or ""
    words = template.split()
    if words and words[0].rsplit("/", 1)[-1] in SHELLS and "{files}" in template:
        return [template.replace("{files}", shlex.quote(str(f))) for f in files]
    return [template.replace("{files}", " ".join(str(f) for f in files))]


def _manifest(run_dir: Path, task_no: int) -> Path:
    """Where a task's lock file is kept."""
    return Path(run_dir) / "tasks" / str(task_no) / "checks.lock.json"


# ported from reference/v8/phoenix/checks.py:104
def file_sha256(path: Path) -> str:
    """The sha256 (hex) of a plain file; raises OSError for a symlink or a missing file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _files_in(worktree: Path, folder: str) -> list[str]:
    """Every file path (repo-relative, sorted) under a folder of the worktree."""
    root = Path(worktree) / folder
    found = []
    for dirpath, _dirs, names in os.walk(root):
        found += [(Path(dirpath) / n).relative_to(worktree).as_posix() for n in names]
    return sorted(found)


def lock(run_dir: Path, task_no: int, worktree: Path, paths: list[str]) -> dict:
    """Fingerprint the given repo-relative files and save the manifest in the run folder."""
    folder = os.path.commonpath([os.path.dirname(p) for p in paths]) if paths else ""
    data = {"dir": folder, "files": {p: file_sha256(Path(worktree) / p) for p in sorted(paths)}}
    atomic.write_json(_manifest(run_dir, task_no), data)
    return data


def _read(run_dir: Path, task_no: int) -> dict | None:
    """The saved manifest, or None when the task has none."""
    return atomic.read_json(_manifest(run_dir, task_no), None)


def verify(run_dir: Path, task_no: int, worktree: Path) -> list[str]:
    """Plain-English problems with the locked checks (changed, deleted, added); [] when untouched."""
    data = _read(run_dir, task_no)
    if not data:
        return []
    problems, locked = [], data.get("files", {})
    for path, digest in locked.items():
        try:
            now = file_sha256(Path(worktree) / path)
        except OSError:
            problems.append(f"The locked check {path} was deleted")
            continue
        if now != digest:
            problems.append(f"The locked check {path} was changed")
    folder = data.get("dir", "")
    if folder:
        problems += [f"A file was added to the locked checks: {p}"
                     for p in _files_in(worktree, folder) if p not in locked]
    return problems


def locked_paths(run_dir: Path) -> list[str]:
    """Every locked file of the run (all tasks) plus each checks folder, for the Diff rules."""
    found: list[str] = []
    for manifest in sorted((Path(run_dir) / "tasks").glob("*/checks.lock.json")):
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        found += list(data.get("files", {}))
        if data.get("dir"):
            found.append(data["dir"].rstrip("/") + "/")
    return found
