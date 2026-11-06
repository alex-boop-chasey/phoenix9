"""A7: small truths on the dashboard (branch, last used, setup facts)."""
import datetime
import json
import os
import subprocess

import pytest

from phoenix9 import paths, project, runs, state
from phoenix9.ops import common, runs as ops_runs

SPEC = "# Spec: Demo\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it works\n"


def git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, env={**os.environ, **(env or {})}).stdout


@pytest.fixture
def proj(tmp_path, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    folder = paths.projects() / "proj"
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# proj\n\nAbout.\n")
    (folder / "phoenix.toml").write_text('profile = "python-script"\n')
    return folder


def make_git(folder, when="2026-03-04T05:06:07+00:00"):
    code = folder / "code"
    code.mkdir()
    git(code, "init", "-q", "-b", "main")
    git(code, "commit", "-q", "--allow-empty", "-m", "first", env={"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when})
    return code


def new_run(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run("proj", f)


def test_run_detail_shows_the_branch_only_while_it_exists(tmp_path, proj):
    code = make_git(proj)
    run_dir = new_run(tmp_path)
    assert ops_runs.detail("proj", run_dir.name)["branch"] is None
    git(code, "branch", f"phoenix/{run_dir.name}")
    assert ops_runs.detail("proj", run_dir.name)["branch"] == f"phoenix/{run_dir.name}"
    git(code, "branch", "-D", f"phoenix/{run_dir.name}")
    assert ops_runs.detail("proj", run_dir.name)["branch"] is None


def test_last_used_follows_run_activity(tmp_path, proj):
    run_dir = new_run(tmp_path)
    project.mark_used("proj")
    used = proj / ".phoenix" / "last-used"
    os.utime(used, (1000, 1000))                       # marked used when the run started, long ago
    os.utime(run_dir / "state.json", (5000, 5000))     # the run did something later
    at, words = project.last_used("proj", 5000 + 120)
    assert at == 5000 and words == "2m ago"


def test_created_and_started_from_come_from_git_when_not_recorded(proj):
    make_git(proj)
    facts = project.setup_facts(proj)
    assert facts["created"] == "2026-03-04" and facts["source"] == "code"
    git(proj / "code", "remote", "add", "origin", "https://github.com/octo/proj.git")
    assert project.setup_facts(proj)["source"] == "repo"


def test_created_falls_back_to_the_folder_and_empty(proj):
    os.utime(proj, (1767225600, 1767225600))           # 2026-01-01
    facts = project.setup_facts(proj)
    assert facts["created"] == "2026-01-01" and facts["source"] == "empty"


def test_recorded_setup_facts_win(proj):
    make_git(proj)
    (proj / ".phoenix").mkdir(exist_ok=True)
    (proj / ".phoenix" / "project.json").write_text(json.dumps({"created": "2025-12-25", "source": "template",
                                                                "template": "site"}))
    facts = project.setup_facts(proj)
    assert facts["created"] == "2025-12-25" and facts["source"] == "template"
