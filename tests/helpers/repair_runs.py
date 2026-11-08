"""Shared set-up for repair tests: a fixture run folder plus a real git repo and worktree in temp folders."""
import json
import subprocess
from pathlib import Path

from phoenix9 import atomic, git, paths

PROJECT = "demo"
RUN = "20261108-073122-demo-run"


def sh(cwd, *args):
    """Run git in cwd with a test identity and return stdout."""
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path) -> Path:
    """A temp repo on main with one commit."""
    code = tmp_path / "code"
    code.mkdir()
    sh(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    sh(code, "add", "-A")
    sh(code, "commit", "-q", "-m", "first")
    return code


def _put(run_dir: Path, name: str, data) -> None:
    """Write one fixture file (json for dict/list, text otherwise)."""
    if isinstance(data, (dict, list)):
        atomic.write_json(run_dir / name, data)
    else:
        atomic.write_text(run_dir / name, data)


def make_run(tmp_path, project: str = PROJECT, run: str = RUN, status: str = "failed") -> dict:
    """Build a run folder in PHOENIX_HOME and a worktree on phoenix/<run>; return the paths."""
    code = make_repo(tmp_path)
    work = git.make_worktree(code, run, paths.work(project, run))
    run_dir = paths.runs(project) / run
    run_dir.mkdir(parents=True)
    _put(run_dir, "state.json", {"run_id": run, "project": project, "status": status, "tasks": {}})
    _put(run_dir, "settings.json", {"model": "fake"})
    _put(run_dir, "plan.json", {"tasks": [{"id": 1, "title": "One"}]})
    _put(run_dir, "things.json", {"things": []})
    _put(run_dir, "spec.json", {"title": "Demo"})
    _put(run_dir, "spec.md", "# Demo\n")
    _put(run_dir, "overrides.json", {})
    _put(run_dir, "gates/q-1.json", {"id": "q-1", "state": "answered", "created": "2026-11-08T07:00:00+00:00", "answer": {"action": "ok"}})
    for k in (1, 2):
        _put(run_dir, f"tasks/1/attempt-{k}/result.json", {"passed": k == 2})
        _put(run_dir, f"tasks/1/attempt-{k}/log.txt", "long log\n")
    return {"code": code, "work": work, "run_dir": run_dir, "project": project, "run": run}
