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


# ---- O28: a chat or the agent cannot start a build with its own safety settings ----

@pytest.mark.parametrize("who", ["chat:demo", "chat:home", "agent"])
@pytest.mark.parametrize("overrides", [{"budget_usd": 0}, {"on_failure": "continue"},
                                       {"steps": {"verify": {"on": False}}}, {"steps.verify.on": False}])
def test_chat_may_not_start_a_build_with_safety_overrides(demo, tmp_path, who, overrides):
    with pytest.raises(common.OpsError, match="may not start a build with its own"):
        ops_runs.start("demo", spec_file(tmp_path), overrides, who=who)
    assert not paths.runs("demo").exists() or not list(paths.runs("demo").iterdir())


@pytest.mark.parametrize("who", ["dashboard", "cli"])
def test_dashboard_and_cli_keep_safety_overrides(demo, tmp_path, who):
    r = ops_runs.start("demo", spec_file(tmp_path), {"budget_usd": 3, "on_failure": "pause"}, who=who)
    got = atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json")
    assert got["budget_usd"] == 3 and got["on_failure"] == "pause"


def test_chat_may_still_give_plain_overrides(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path), {"preset": "full", "steps": {"planner": {"on": False}}},
                       who="chat:demo")
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json")["preset"] == "full"


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


# ---- discard refuses to lose work (open merge request, commits not on main) unless forced ----

def commit_on_branch(work):
    (work / "new.py").write_text("print('work')\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "work")


def test_discard_refuses_a_branch_with_commits_not_on_main(demo, tmp_path):
    run_id, folder, work = failed_run(demo, tmp_path)
    commit_on_branch(work)
    with pytest.raises(ops_runs.WouldLoseWork, match="1 commit") as err:
        ops_runs.discard(run_id)
    assert isinstance(err.value, common.Conflict) and err.value.lost
    assert work.exists() and branches(demo) != "" and not state.load(folder).get("discarded")
    r = ops_runs.discard(run_id, force=True)
    assert r["discarded"] is True and not work.exists() and branches(demo) == ""


@pytest.mark.parametrize("answer", [(0, "OPEN\n", ""), (1, "", "no network")])
def test_discard_refuses_an_open_or_unknown_merge_request(demo, tmp_path, answer):
    run_id, folder, work = failed_run(demo, tmp_path)
    url = "https://github.com/rebirth-wd/demo/pull/7"
    (folder / "merge-request.txt").write_text(url + "\n")
    demo["adapters"].host.script(["gh", "pr", "view", url], *answer)
    with pytest.raises(ops_runs.WouldLoseWork, match="merge request") as err:
        ops_runs.discard(run_id)
    assert url in str(err.value) and work.exists()
    assert ops_runs.discard(run_id, force=True)["discarded"] is True


def test_discard_allows_a_merged_merge_request(demo, tmp_path):
    run_id, folder, work = failed_run(demo, tmp_path)
    url = "https://github.com/rebirth-wd/demo/pull/7"
    (folder / "merge-request.txt").write_text(url + "\n")
    demo["adapters"].host.script(["gh", "pr", "view", url], 0, "MERGED\n", "")
    assert ops_runs.discard(run_id)["discarded"] is True and not work.exists()


def test_cli_discard_needs_force_to_lose_work(demo, tmp_path, capsys):
    run_id, _, work = failed_run(demo, tmp_path)
    commit_on_branch(work)
    code, _, err = run_cmd(capsys, "run", "discard", run_id, "--yes")
    assert code == 1 and "--force" in err and "1 commit" in err and work.exists()
    code, out, _ = run_cmd(capsys, "run", "discard", run_id, "--yes", "--force", "--json")
    assert code == 0 and json.loads(out)["discarded"] is True and not work.exists()


def test_api_discard_needs_force_to_lose_work(demo, tmp_path, api):
    from test_api_server import POST_HEADERS
    run_id, _, work = failed_run(demo, tmp_path)
    commit_on_branch(work)
    status, body = api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {"confirm": True})
    assert status == 409 and body["needs_force"] is True and "1 commit" in body["message"]
    assert body["would_lose"] and work.exists()
    status, body = api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {"confirm": True, "force": "yes"})
    assert status == 400 and work.exists()
    status, body = api(f"/api/runs/demo/{run_id}/discard", "POST", POST_HEADERS, {"confirm": True, "force": True})
    assert status == 200 and body["data"]["discarded"] is True and not work.exists()


def test_discard_checks_the_same_permission_as_stop(demo, tmp_path):
    run_id, folder, work = failed_run(demo, tmp_path)
    with pytest.raises(common.OpsError, match="may not discard"):
        ops_runs.discard(run_id, who="chat:home")
    assert work.exists() and not state.load(folder).get("discarded")
    toml = demo["folder"] / "phoenix.toml"
    toml.write_text(toml.read_text() + 'home_chat_may_answer = ["escalation"]\n')
    assert ops_runs.discard(run_id, who="chat:home")["discarded"] is True


@pytest.mark.parametrize("who", ["cli", "dashboard"])
def test_discard_allowed_callers(demo, tmp_path, who):
    run_id, _, _ = failed_run(demo, tmp_path)
    assert ops_runs.discard(run_id, who=who)["discarded"] is True


def _grant(run_id, steps, who="chat:home"):
    """Ask as `who` for a one-time unlock and approve it from the dashboard."""
    from phoenix9.ops import gates as ops_gates, repair as ops_repair
    asked = ops_repair.request_unlock(run_id, steps, "the run is stuck", who=who)
    ops_gates.answer(asked["gate"], "approve", who="dashboard")


def test_a_chat_may_discard_once_with_alex_approval(demo, tmp_path):
    run_id, folder, work = failed_run(demo, tmp_path)
    _grant(run_id, ["stop"])                                  # a grant for something else does not count
    with pytest.raises(common.OpsError, match="may not discard"):
        ops_runs.discard(run_id, who="chat:home")
    _grant(run_id, ["discard"])
    with pytest.raises(common.OpsError, match="may not discard"):
        ops_runs.discard(run_id, who="chat:demo")              # another asker: not its grant
    assert ops_runs.discard(run_id, who="chat:home")["discarded"] is True
    used = [e for e in events.read(folder / "events.jsonl")
            if e["type"] == "repair.unlock" and e["data"]["what"] == "used"]
    assert len(used) == 1 and used[0]["data"]["steps"] == ["discard"]
    assert "Repaired by the agent with Alex's approval" in used[0]["data"]["text"]


def test_a_discard_grant_is_for_one_run_only(demo, tmp_path):
    first, _, _ = failed_run(demo, tmp_path)
    second, folder, work = failed_run(demo, tmp_path)
    _grant(first, ["discard"])
    with pytest.raises(common.OpsError, match="may not discard"):
        ops_runs.discard(second, who="chat:home")
    assert work.exists() and not state.load(folder).get("discarded")
