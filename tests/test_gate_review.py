"""Tests for the merge review of a merge gate: facts, diff, safety flag, scrubbing, fallbacks."""
import subprocess

import pytest

from phoenix9 import gates, paths, runs, scrub, state
from phoenix9.ops import common, gates as ops_gates

SPEC = "# Spec: Demo\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it works fine\n"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def merge_gate(tmp_path):
    """A project with a code repo, a run branch with changes, and an open merge gate."""
    project = paths.projects() / "alpha"
    code = project / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("one\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    spec = tmp_path / "spec.md"
    spec.write_text(SPEC)
    folder = runs.create_run("alpha", spec)
    run_id = state.load(folder)["run_id"]
    git(code, "checkout", "-q", "-b", f"phoenix/{run_id}")
    (code / "a.txt").write_text("one\ntwo\n")
    (code / "secrets.txt").write_text("token=sk-live-abcdefgh12345\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "second")
    git(code, "checkout", "-q", "main")
    (folder / "summary.md").write_text("# Demo\n- all done\n")
    state.set_task(folder, 1, status="passed", tries=2)
    gate = gates.open_gate(folder, kind="merge", title="Merge Demo?", why="all passed")
    return folder, gate, code


def test_review_has_facts_and_files(merge_gate):
    folder, gate, _ = merge_gate
    r = ops_gates.review(gate["id"])
    assert r["title"] == "Merge Demo?" and "all done" in r["summary"]
    assert r["tasks"]["passed"] == 1 and r["tasks"]["total"] == 1
    assert r["tasks"]["retried"][0]["number"] == 1
    by = {f["path"]: f for f in r["files"]}
    assert by["a.txt"]["added"] == 1 and "+two" in by["a.txt"]["diff"]
    assert r["added"] == 2 and r["safety"]["flag"] is False


def test_review_safety_flag(merge_gate, monkeypatch):
    _, gate, _ = merge_gate
    monkeypatch.setattr(ops_gates.settings, "load_project", lambda p: {"safety_files": ["secrets.*"]})
    r = ops_gates.review(gate["id"])
    assert r["safety"] == {"flag": True, "files": ["secrets.txt"]}
    assert {f["path"]: f["safety"] for f in r["files"]}["secrets.txt"] is True


def test_review_scrubs_secrets(merge_gate):
    _, gate, _ = merge_gate
    scrub.add_secrets(["sk-live-abcdefgh12345"])
    text = str(ops_gates.review(gate["id"]))
    assert "sk-live-abcdefgh12345" not in text and "[secret]" in text


def test_review_falls_back_to_patch_files(merge_gate):
    folder, gate, code = merge_gate
    run_id = state.load(folder)["run_id"]
    git(code, "branch", "-q", "-D", f"phoenix/{run_id}")
    patch = folder / "tasks" / "1" / "attempt-1"
    patch.mkdir(parents=True)
    (patch / "diff.patch").write_text("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
    r = ops_gates.review(gate["id"])
    assert [(f["path"], f["added"], f["removed"]) for f in r["files"]] == [("x.py", 1, 1)]


def test_review_refuses_other_kinds_and_unknown(merge_gate):
    folder, _, _ = merge_gate
    other = gates.open_gate(folder, kind="plan", title="Plan?", why="x")
    with pytest.raises(common.OpsError):
        ops_gates.review(other["id"])
    with pytest.raises(common.NotFound):
        ops_gates.review("20260101-000000-nope.1")
