"""Run controls: the spec's Preset line (B5) and `phoenix run discard` (B1)."""
import json
import subprocess

import pytest

from test_api_server import api, dist  # noqa: F401  (fixtures)

from phoenix9 import atomic, events, paths, state
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.ops import runs as ops_runs

SPEC = """# Add a hello script
Project: demo
{preset}
## Task 1: Hello
Make a script called hello.py that prints hello.
Done when:
- `python3 hello.py`
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def demo(phoenix_env, tmp_path, monkeypatch, adapters):
    """A project called demo (code/ is a git repo) and fake adapters for ops."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    folder = phoenix_env["projects"] / "demo"
    (folder / "code").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# Demo\n")
    (folder / "phoenix.toml").write_text('preset = "quick"\nprofile = "python-script"\n')
    code = folder / "code"
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hi\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return {"folder": folder, "code": code, "adapters": adapters}


def spec_file(tmp_path, preset_line=""):
    p = tmp_path / "spec.md"
    p.write_text(SPEC.format(preset=preset_line + "\n" if preset_line else ""))
    return p


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# ---- B5: the spec's Preset line ----

def test_spec_preset_is_used_when_no_override(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path, "Preset: full"))
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") == {"preset": "full"}


def test_explicit_preset_beats_the_spec(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path, "Preset: full"), {"preset": "simple"})
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") == {"preset": "simple"}


def test_no_preset_line_means_no_override(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path))
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") is None


# ---- B1: phoenix run discard ----

def failed_run(demo, tmp_path, status="failed"):
    """A run that ended with this status and still has its worktree and local branch."""
    run_id = ops_runs.start("demo", spec_file(tmp_path))["run_id"]
    folder = paths.runs("demo") / run_id
    work = paths.work("demo", run_id)
    work.parent.mkdir(parents=True, exist_ok=True)
    git(demo["code"], "worktree", "add", "-q", "-b", f"phoenix/{run_id}", str(work))
    state.set_status(folder, status)
    return run_id, folder, work


def branches(demo):
    return git(demo["code"], "branch", "--list", "phoenix/*").strip()


def test_discard_removes_worktree_and_branch_and_marks_the_run(demo, tmp_path):
    run_id, folder, work = failed_run(demo, tmp_path)
    r = ops_runs.discard(run_id, who="alex")
    assert r["discarded"] is True and r["status"] == "failed"
    assert not work.exists() and branches(demo) == ""
    st = state.load(folder)
    assert st["discarded"] is True and st["discarded_by"] == "alex" and st["discarded_at"]
    assert st["status"] == "failed"
    ev = [e for e in events.read(folder / "events.jsonl") if e["type"] == "run.discarded"]
    assert ev and ev[0]["data"]["who"] == "alex"
    assert f"run discard {run_id}" in (paths.logs() / "commands.jsonl").read_text()


def test_discard_a_stopped_run_and_twice_is_refused(demo, tmp_path):
    run_id, _, _ = failed_run(demo, tmp_path, "stopped")
    ops_runs.discard(run_id)
    with pytest.raises(common.Conflict, match="already discarded"):
        ops_runs.discard(run_id)


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "paused-limit", "done"])
def test_discard_refuses_runs_that_are_not_failed_or_stopped(demo, tmp_path, status):
    run_id, _, work = failed_run(demo, tmp_path, status)
    with pytest.raises(common.OpsError, match=status):
        ops_runs.discard(run_id)
    assert work.exists() and branches(demo) != ""


def test_discard_checks_the_project(demo, tmp_path):
    run_id, _, _ = failed_run(demo, tmp_path)
    with pytest.raises(common.NotFound):
        ops_runs.discard(run_id, project="other")


def test_cli_discard_needs_yes(demo, tmp_path, capsys):
    run_id, folder, work = failed_run(demo, tmp_path)
    code, _, err = run_cmd(capsys, "run", "discard", run_id)
    assert code == 1 and "--yes" in err and work.exists()
    code, out, _ = run_cmd(capsys, "run", "discard", run_id, "--yes", "--json")
    assert code == 0 and json.loads(out)["discarded"] is True and not work.exists()


def test_builds_and_detail_say_discarded(demo, tmp_path):
    run_id, _, _ = failed_run(demo, tmp_path)
    ops_runs.discard(run_id)
    assert ops_runs.builds("demo")[0]["discarded"] is True
    assert ops_runs.detail("demo", run_id)["discarded"] is True


def test_api_discard(demo, tmp_path, api):
    from test_api_server import POST_HEADERS
    run_id, _, work = failed_run(demo, tmp_path)
    assert api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {})[0] == 400
    status, body = api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {"confirm": True})
    assert status == 200 and body["data"]["discarded"] is True and not work.exists()
    status, body = api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {"confirm": True})
    assert status == 409
