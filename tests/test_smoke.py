"""Smoke runs end to end with fake Claude sessions and a fake Docker that really runs the checks."""
import subprocess
from pathlib import Path

import pytest

from fakes import RealCheckDocker, fake_adapters
from phoenix9 import events, paths, state, watch
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.runner import Runner

ROOT = Path(__file__).resolve().parent.parent

HELLO = 'print("hello")\n'
TEST_HELLO = '''import subprocess, sys
from pathlib import Path


def test_prints_hello():
    script = Path(__file__).resolve().parent.parent / "hello.py"
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True).stdout
    assert out.strip() == "hello"
'''
HELLO_NAME = '''import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="")
args = parser.parse_args()
print(("hello " + args.name).strip())
'''


def git(cwd, *args):
    """Run plain git in a test repo and return its output."""
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                         capture_output=True, text=True, check=True)
    return out.stdout


@pytest.fixture
def smoke(phoenix_env, tmp_path, monkeypatch):
    """A project with a real git repo, the python-script profile, and adapters with scripted sessions."""
    adapters = fake_adapters(tmp_path)
    adapters.docker = RealCheckDocker()
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(ROOT))
    project = phoenix_env["projects"] / "smoke"
    code = project / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "initial")
    (project / "phoenix.toml").write_text('preset = "simple"\nprofile = "python-script"\n')
    (project / "CLAUDE.md").write_text("# Smoke\n")
    return {"adapters": adapters, "project": project, "code": code}


def play(smoke, sessions):
    """Script the Builder sessions, start the run through the CLI and watch until it ends."""
    adapters = smoke["adapters"]
    adapters.claude.sessions = [{"files": f, "cost_usd": 0.5} for f in sessions]
    assert main(["run", "start", "smoke", "--spec", str(ROOT / "plans" / "smoke.md"), "--json"]) == 0
    runner = Runner(adapters, ROOT)
    for _ in range(5):
        if watch.watch_once(adapters, runner) is None:
            break
    run_dir = next(paths.runs("smoke").iterdir())
    return run_dir, state.load(run_dir)


def test_smoke_run_builds_commits_and_merges(smoke):
    run_dir, st = play(smoke, [{"hello.py": HELLO}, {"tests/test_hello.py": TEST_HELLO},
                               {"hello.py": HELLO_NAME}])
    code = smoke["code"]
    assert st["status"] == "done", st
    log = git(code, "log", "--format=%B%x00", "main").split("\0")
    commits = [c for c in log if "Phoenix-Run" in c]
    assert len(commits) == 3
    for n in (1, 2, 3):
        assert any(f"Phoenix-Task: {n}" in c and f"Phoenix-Run: {st['run_id']}" in c for c in commits)
    assert git(code, "branch", "--list", f"phoenix/{st['run_id']}").strip() == ""   # merged, so the branch is gone
    assert (code / "hello.py").read_text() == HELLO_NAME
    summary = (run_dir / "summary.md").read_text()
    assert summary.count("passed") >= 3 and all(f"Task {n}:" in summary for n in (1, 2, 3))
    assert "Cost: $1.50" in summary
    seen = events.read(run_dir / "events.jsonl")
    for group in ("run-start", "task", "run-finish"):
        for line in [x for x in st["steps"] if x["group"] == group]:
            kinds = [e["type"] for e in seen if e.get("step") == line["step"] and e.get("task") == line["task"]]
            assert "run.step.started" in kinds and "run.step.finished" in kinds, line
    assert smoke["adapters"].notify.messages and "3 passed, 0 failed, 0 skipped" in smoke["adapters"].notify.messages[0]


def test_smoke_env_file_fails_task_and_main_stays(smoke):
    code = smoke["code"]
    (smoke["project"] / "phoenix.toml").write_text(
        'preset = "simple"\nprofile = "python-script"\nmax_tries = 1\non_failure = "continue"\n')
    before = git(code, "rev-parse", "main")
    run_dir, st = play(smoke, [{"hello.py": HELLO}, {"tests/test_hello.py": TEST_HELLO, ".env": "KEY=1\n"}])
    assert st["status"] == "waiting"   # a failed task forces the merge to ask (step 9)
    assert [st["tasks"][n]["status"] for n in ("1", "2", "3")] == ["passed", "failed", "skipped"]
    diff_line = next(x for x in st["steps"] if x["step"] == "diff-rules" and x["task"] == 2)
    assert diff_line["status"] == "failed" and ".env" in diff_line["note"]
    assert git(code, "rev-parse", "main") == before
    assert not (code / "hello.py").exists()
    assert st["current"]["gate"]   # the merge gate is open; Notify runs after it is answered
