"""Alex-approved repair unlocks: the agent asks, only the dashboard answers, the grant is used once for exactly that."""
from datetime import timedelta

import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, gates, paths, resolve, settings, state
from phoenix9.__main__ import main
from phoenix9.library import load_library
from phoenix9.ops import common, gates as ops_gates, repair as ops
from phoenix9.repair import safety, unlock


def make(tmp_path, project="demo", run="20261108-073122-demo-run"):
    """A failed run with one failed task whose checks are locked, and the real library's settings and plan."""
    r = make_run(tmp_path, project=project, run=run)
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    task = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["SPEC_PROBLEM: bad checks"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": task}, steps=[]))
    atomic.write_json(r["run_dir"] / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {"tests/a.py": "x"}})
    return r


def text(r, *lines):
    return f"# Repair {r['run']}\n\nWhy: test\n\n## Steps\n\n" + "\n".join(f"- {s}" for s in lines) + "\n"


FORCED = ("add a note to task 1: look again", "force")


def approve(r, steps=("force",), who="agent"):
    """Ask as `who` and approve from the dashboard; returns the question."""
    asked = ops.request_unlock(r["run"], list(steps), "the checks are stuck", who=who)
    ops_gates.answer(asked["gate"], "approve", who="dashboard")
    return asked


def unlock_events(r, what):
    return [e for e in events.read(r["run_dir"] / "events.jsonl")
            if e["type"] == "repair.unlock" and e["data"]["what"] == what]


def test_refusal_text_says_how_to_ask():
    assert safety.REFUSAL == ("That needs Alex's approval: ask with `phoenix repair request-unlock`; "
                              "Alex approves it in the dashboard.")


def test_request_opens_an_alex_only_question_and_leaves_the_run_alone(tmp_path):
    r = make(tmp_path)
    before = state.load(r["run_dir"])
    asked = ops.request_unlock(r["run"], ["reset-worktree", "replace-spec"], "the worktree is broken", who="agent")
    assert asked["title"] == (f"The agent asks to reset the worktree and replace the spec on {r['run']}: "
                              "the worktree is broken")
    assert state.load(r["run_dir"])["status"] == before["status"] == "failed"
    shown = [g for g in gates.list_gates() if g["id"] == asked["gate"]]
    assert shown and shown[0]["kind"] == "repair-unlock" and shown[0]["actions"] == ["approve", "deny"]
    assert shown[0]["unlock_steps"] == ["reset-worktree", "replace-spec"]
    with pytest.raises(common.OpsError, match="already a request"):
        ops.request_unlock(r["run"], ["force"], "again", who="agent")


@pytest.mark.parametrize("who", ["agent", "chat:home", "chat:demo", "cli"])
def test_only_the_dashboard_may_answer(tmp_path, who):
    r = make(tmp_path)
    (paths.projects() / r["project"] / "phoenix.toml").write_text('home_chat_may_answer = ["repair-unlock", "escalation"]\n')
    asked = ops.request_unlock(r["run"], ["force"], "stuck", who="agent")
    for action in ("approve", "deny"):
        with pytest.raises(common.OpsError, match="may not answer"):
            ops_gates.answer(asked["gate"], action, who=who)
    assert not unlock.grants_path(r["run_dir"]).exists()


@pytest.mark.parametrize("who", ["dashboard", "cli"])
def test_alex_needs_no_approval(tmp_path, who):
    r = make(tmp_path)
    with pytest.raises(common.OpsError, match="do this repair yourself"):
        ops.request_unlock(r["run"], ["force"], "stuck", who=who)


@pytest.mark.parametrize("steps,why", [([], "x"), (["turn-off-step"], "x"), (["mark-done"], "x"),
                                       (["force"], ""), (["force"], "a\nb")])
def test_bad_requests_are_refused(tmp_path, steps, why):
    r = make(tmp_path)
    with pytest.raises(common.OpsError):
        ops.request_unlock(r["run"], steps, why, who="agent")
    assert not gates.list_gates()


def test_a_project_chat_may_ask_only_about_its_own_runs(tmp_path):
    r = make(tmp_path)
    with pytest.raises(common.Conflict, match="its own project"):
        ops.request_unlock(r["run"], ["force"], "stuck", who="chat:other")
    assert ops.request_unlock(r["run"], ["force"], "stuck", who="chat:demo")["gate"]


def test_approved_grant_is_used_once_and_leaves_a_record(tmp_path):
    r = make(tmp_path)
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, *FORCED), who="agent")
    approve(r)
    assert unlock_events(r, "approved")
    done = ops.apply_text(r["run"], text(r, *FORCED), who="agent")
    assert done["ok"]
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, *FORCED), who="agent")
    used = unlock_events(r, "used")
    assert len(used) == 1 and used[0]["data"]["steps"] == ["force"]
    assert used[0]["data"]["text"].startswith("Repaired by the agent with Alex's approval at ")
    applied = [e for e in events.read(r["run_dir"] / "events.jsonl") if e["type"] == "repair.applied"]
    assert applied[-1]["data"]["alex_approved"] == ["force"]
    record = unlock.record_path(r["run_dir"]).read_text()
    assert "Alex allowed the agent once to force a repair past its check" in record
    assert "Repaired by the agent with Alex's approval at" in record
    assert gates.run_repaired(r["run_dir"])


def test_a_dry_run_does_not_use_the_grant(tmp_path):
    r = make(tmp_path)
    approve(r)
    assert ops.apply_text(r["run"], text(r, *FORCED), who="agent", dry_run=True)["dry_run"]
    assert not unlock_events(r, "used")
    assert ops.apply_text(r["run"], text(r, *FORCED), who="agent")["ok"]


def test_grant_matches_only_its_run_its_steps_and_its_asker(tmp_path):
    r = make(tmp_path)
    other = make_run_beside(tmp_path)
    approve(r, steps=("force",))
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(other["run"], text(other, *FORCED), who="agent")
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, "rewrite the checks of task 1 because wrong"), who="agent")
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, *FORCED), who="chat:demo")
    assert not unlock_events(r, "used")
    assert ops.apply_text(r["run"], text(r, *FORCED), who="agent")["ok"]


def make_run_beside(tmp_path):
    """A second failed run of the same project, with its own folder."""
    run = "20261108-080000-other-run"
    run_dir = paths.runs("demo") / run
    atomic.write_json(run_dir / "state.json", {"run_id": run, "project": "demo", "status": "failed",
                                               "tasks": {"1": {**state.new_task("One"), "status": "failed"}}})
    return {"run": run, "run_dir": run_dir}


def test_a_safety_step_is_never_unlocked(tmp_path):
    r = make(tmp_path)
    approve(r, steps=("force",))
    with pytest.raises(common.Conflict, match="even with approval"):
        ops.apply_text(r["run"], text(r, "turn off step diff-rules for this run", "force"), who="agent")
    assert not unlock_events(r, "used")


def test_grant_expires_after_thirty_minutes(tmp_path, monkeypatch):
    r = make(tmp_path)
    approve(r)
    real = unlock._now
    monkeypatch.setattr(unlock, "_now", lambda: real() + timedelta(minutes=unlock.GRANT_MINUTES, seconds=1))
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, *FORCED), who="agent")
    unlock.expire_old(r["run_dir"])
    assert len(unlock_events(r, "expired")) == 1
    assert "ran out unused" in unlock.record_path(r["run_dir"]).read_text()
    assert unlock.records(r["run_dir"])[0]["expired_at"] and not unlock.records(r["run_dir"])[0]["used_at"]
    assert not gates.run_repaired(r["run_dir"])


def test_denied_request_gives_no_grant_and_is_recorded(tmp_path):
    r = make(tmp_path)
    asked = ops.request_unlock(r["run"], ["force"], "stuck", who="agent")
    ops_gates.answer(asked["gate"], "deny", who="dashboard")
    assert unlock_events(r, "denied")
    assert "did not allow" in unlock.record_path(r["run_dir"]).read_text()
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.apply_text(r["run"], text(r, *FORCED), who="agent")


def test_a_chat_may_force_with_a_grant_even_without_project_permission(tmp_path):
    r = make(tmp_path)
    approve(r, who="chat:demo")
    assert ops.apply_text(r["run"], text(r, *FORCED), who="chat:demo")["ok"]
    assert unlock_events(r, "used")[0]["data"]["who"] == "chat:demo"


def test_run_detail_lists_the_used_grant(tmp_path):
    from phoenix9.ops import runs as ops_runs
    r = make(tmp_path)
    approve(r)
    ops.apply_text(r["run"], text(r, *FORCED), who="agent")
    used = ops_runs._unlocks_used(r["run_dir"])
    assert len(used) == 1 and used[0]["steps"] == ["force"] and used[0]["who"] == "agent"


def test_cli_request_unlock(tmp_path, monkeypatch, capsys):
    r = make(tmp_path)
    monkeypatch.setenv("PHOENIX_WHO", "chat:demo")
    code = main(["repair", "request-unlock", r["run"], "--steps", "reset-worktree,force", "--why", "stuck"])
    out = capsys.readouterr().out
    assert code == 0 and "The agent asks to reset the worktree and force a repair past its check" in out
    asked = [g for g in gates.list_gates() if g["kind"] == "repair-unlock"]
    assert asked[0]["asked_by"] == "chat:demo"


def test_agent_rewrites_locked_checks_only_with_a_grant(tmp_path):
    r = make(tmp_path)
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.rewrite_checks(r["run"], 1, "the checks test the wrong file", who="agent")
    approve(r, steps=("unlock-checks",))
    done = ops.rewrite_checks(r["run"], 1, "the checks test the wrong file", who="agent")
    assert not done["refused"], done
    assert unlock_events(r, "used")[0]["data"]["steps"] == ["unlock-checks"]
    atomic.write_json(r["run_dir"] / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {"tests/a.py": "y"}})
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.rewrite_checks(r["run"], 1, "again", who="agent")
