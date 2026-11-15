"""The agent's own fix on a hand-off: handoff-fix (try again / rewrite the checks once) and handoff-give-up."""
import json

import pytest

from helpers import repair_runs as rr
from helpers.scripted import fail, on
from phoenix9 import atomic, events, gates, handoff, state
from phoenix9.ops import common, gates as ops_gates, handoff as ops, repair as repair_ops
from phoenix9.repair import unlock
from phoenix9.stepctx import StepResult
from test_api_server import POST_HEADERS, api, dist  # noqa: F401 - fixtures
from test_handoff import only_gate, project, runner, sent, start  # noqa: F401 - the same worlds as test_handoff

LOCKED = "tests/test_one.py"
EVIDENCE = f"{LOCKED} fails: it reads the coloured output of the tool, which changes on every run"


@pytest.fixture
def same(adapters, monkeypatch):
    """Ops use the runner's fake adapters, so Telegram lines and outcome posts can be read back."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def handed_run(tmp_path, runner, reason="flaky", locked=True):
    """A run waiting on task 1's escalation question, handed to the agent; checks locked when asked."""
    on("builder", 1, 1, fail(reason), StepResult("pass", produces={"diff": "builder:1"}))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    if locked:
        atomic.write_json(run_dir / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {LOCKED: "x"}})
    return run_dir, only_gate(run_dir)


def kinds(run_dir, kind):
    return [e for e in events.read(run_dir / "events.jsonl") if e["type"] == kind]


def outcomes(calls):
    return [json.loads(c["body"]) for c in calls if c["url"].endswith("/handoffs/outcome")]


def live_grants(run_dir):
    return [g for g in unlock.records(run_dir) if not g.get("used_at") and not g.get("expired_at")]


def test_retry_answers_acknowledged_with_the_note_and_the_run_reruns_once(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner)
    done = ops.fix("proj", run_dir.name, 1, "retry", note="Use the\n\nsecond config file.", who="agent")
    assert done["action"] == "retry" and done["gate"] == g["id"]
    answer = gates.poll(run_dir, g["id"])
    assert answer["action"] == "acknowledged" and answer["who"] == "agent"
    assert answer["note"] == "Use the second config file."
    assert handoff.current(run_dir, 1)["action"] == "retry"
    (acted,) = kinds(run_dir, "handoff.acted")
    assert acted["data"]["action"] == "retry" and acted["data"]["who"] == "agent"
    assert runner.drive(run_dir) == "done"
    t = state.load(run_dir)["tasks"]["1"]
    assert t["status"] == "passed" and t["tries"] == 2
    assert "Note from agent: Use the second config file." in t["failures"]
    assert handoff.load(run_dir, 1)["items"][-1]["state"] == "fixed"


def test_a_long_note_is_refused(tmp_path, runner, sent, same):
    run_dir, _g = handed_run(tmp_path, runner)
    with pytest.raises(common.OpsError, match="under 2000"):
        ops.fix("proj", run_dir.name, 1, "retry", note="x" * 2001)


def test_rewrite_checks_removes_them_records_the_grant_and_the_run_goes_on(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner, reason=EVIDENCE)
    done = ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="the check reads coloured output", who="agent")
    assert done["action"] == "rewrite-checks"
    assert not (run_dir / "tasks" / "1" / "checks.lock.json").exists()
    record = unlock.record_path(run_dir).read_text()
    assert ("Allowed for the agent on a hand-off of task 1 (Alex's standing rule of 2026-11-15): "
            "the check reads coloured output") in record
    assert "Repaired by the agent under the hand-off rule at " in record
    assert "with Alex's approval" not in record
    assert live_grants(run_dir) == []
    (acted,) = kinds(run_dir, "handoff.acted")
    assert acted["data"]["action"] == "rewrite-checks" and acted["data"]["why"] == "the check reads coloured output"
    assert handoff.current(run_dir, 1)["rewrote_checks"] is True and handoff.rewrite_used(run_dir, 1)
    assert gates.poll(run_dir, g["id"])["action"] == "closed"
    t = state.load(run_dir)["tasks"]["1"]
    assert t["status"] == "pending" and t["tries"] == 0 and not t.get("gate")
    assert runner.drive(run_dir) == "done"
    assert state.load(run_dir)["tasks"]["1"]["status"] == "passed"
    (item,) = handoff.load(run_dir, 1)["items"]
    assert item["state"] == "fixed" and item["action"] == "rewrite-checks"


def test_a_second_rewrite_on_the_same_task_is_refused(tmp_path, runner, sent, same):
    on("builder", 1, None, fail(EVIDENCE))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    atomic.write_json(run_dir / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {LOCKED: "x"}})
    ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="the check reads coloured output")
    assert runner.drive(run_dir) == "waiting"                  # failed again: handed over a second time
    assert handoff.current(run_dir, 1) is not None
    atomic.write_json(run_dir / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {LOCKED: "y"}})
    with pytest.raises(common.Conflict, match="already rewrote this task's checks once"):
        ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="again")
    assert (run_dir / "tasks" / "1" / "checks.lock.json").exists()


def test_rewrite_without_evidence_is_refused_and_leaves_no_live_grant(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner, reason="the builder ran out of time")
    with pytest.raises(common.Conflict, match="the checks are not the problem"):
        ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="I think the check is wrong")
    assert (run_dir / "tasks" / "1" / "checks.lock.json").exists()
    assert live_grants(run_dir) == [] and unlock.find(run_dir, "agent", ["unlock-checks"]) is None
    assert gates.poll(run_dir, g["id"]) is None and not handoff.rewrite_used(run_dir, 1)
    assert kinds(run_dir, "handoff.acted") == []
    with pytest.raises(common.Conflict, match="needs Alex's approval"):    # nothing left for a plain repair to use
        repair_ops.rewrite_checks(run_dir.name, 1, "the checks are wrong", who="agent")


def test_a_hand_off_grant_only_covers_its_own_task(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner, reason=EVIDENCE)
    grant = unlock.grant_for_handoff(run_dir, 1, "the check reads coloured output", gate=g["id"])
    assert unlock.find(run_dir, "agent", ["unlock-checks"]) is None            # no task named
    assert unlock.find(run_dir, "agent", ["unlock-checks"], tasks=[2]) is None
    assert unlock.find(run_dir, "agent", ["unlock-checks"], tasks=[1, 2]) is None
    assert unlock.use(run_dir, "agent", ["unlock-checks"], tasks=[2]) is None
    atomic.write_json(run_dir / "tasks" / "2" / "checks.lock.json", {"dir": "tests", "files": {"tests/test_two.py": "x"}})
    with pytest.raises(common.Conflict, match="needs Alex's approval"):       # a repair of another task
        repair_ops.rewrite_checks(run_dir.name, 2, "tests/test_two.py is wrong", who="agent")
    assert (run_dir / "tasks" / "2" / "checks.lock.json").exists()
    assert unlock.find(run_dir, "agent", ["unlock-checks"], tasks=[1])["gate"] == grant["gate"]
    assert unlock.use(run_dir, "agent", ["unlock-checks"], tasks=[1])["handoff_task"] == 1


def test_a_crash_in_the_rewrite_takes_the_grant_back_and_allows_no_second_rewrite(tmp_path, runner, sent, same, monkeypatch):
    run_dir, _g = handed_run(tmp_path, runner, reason=EVIDENCE)

    def crash(*a, **k):
        assert handoff.rewrite_used(run_dir, 1)            # "rewrote once" is on record before the rewrite starts
        raise RuntimeError("the power went out")

    real_apply = repair_ops.apply_text
    monkeypatch.setattr(repair_ops, "apply_text", crash)
    with pytest.raises(RuntimeError):
        ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="the check reads coloured output")
    assert live_grants(run_dir) == [] and unlock.find(run_dir, "agent", ["unlock-checks"], tasks=[1]) is None
    assert "The hand-off allowance was taken back" in unlock.record_path(run_dir).read_text()
    monkeypatch.setattr(repair_ops, "apply_text", real_apply)
    with pytest.raises(common.Conflict, match="already rewrote this task's checks once"):
        ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="the check reads coloured output")
    assert (run_dir / "tasks" / "1" / "checks.lock.json").exists()


def test_rewrite_needs_a_reason(tmp_path, runner, sent, same):
    run_dir, _g = handed_run(tmp_path, runner, reason=EVIDENCE)
    with pytest.raises(common.OpsError, match="Give a reason"):
        ops.fix("proj", run_dir.name, 1, "rewrite-checks", why="")


@pytest.mark.parametrize("action", ["skip", "stop", "budget", "merge", "acknowledged", ""])
def test_other_actions_are_refused(tmp_path, runner, sent, same, action):
    run_dir, _g = handed_run(tmp_path, runner)
    with pytest.raises(common.OpsError, match="retry, rewrite-checks"):
        ops.fix("proj", run_dir.name, 1, action, why="x")


def test_refused_unless_the_caller_is_the_agent(tmp_path, runner, sent, same):
    run_dir, _g = handed_run(tmp_path, runner)
    for who in ("dashboard", "cli", "chat:home", "chat:proj"):
        with pytest.raises(common.Conflict):
            ops.fix("proj", run_dir.name, 1, "retry", who=who)
        with pytest.raises(common.Conflict):
            ops.give_up("proj", run_dir.name, 1, "x", who=who)


def test_refused_for_another_task_run_or_project(tmp_path, runner, sent, same):
    run_dir, _g = handed_run(tmp_path, runner)
    for project, run_id, task in (("proj", run_dir.name, 2), ("proj", "20261101-000000-other", 1),
                                  ("other", run_dir.name, 1)):
        with pytest.raises(common.Conflict, match="not handed to the agent"):
            ops.fix(project, run_id, task, "retry")
        with pytest.raises(common.Conflict, match="not handed to the agent"):
            ops.give_up(project, run_id, task, "x")


def test_refused_when_already_answered(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner)
    ops_gates.answer(g["id"], "acknowledged", who="dashboard")
    with pytest.raises(common.Conflict, match="not handed to the agent"):
        ops.fix("proj", run_dir.name, 1, "retry")


def test_refused_when_the_gate_is_not_handed(tmp_path, runner, sent, same):
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path, on_failure="pause")
    assert runner.drive(run_dir) == "waiting"
    with pytest.raises(common.Conflict, match="not handed to the agent"):
        ops.fix("proj", run_dir.name, 1, "retry")
    with pytest.raises(common.Conflict, match="not handed to the agent"):
        ops.give_up("proj", run_dir.name, 1, "x")


def test_give_up_turns_the_question_into_alexs(tmp_path, runner, sent, same):
    run_dir, g = handed_run(tmp_path, runner)
    done = ops.give_up("proj", run_dir.name, 1, "it needs a budget change", who="agent")
    assert done["state"] == "gave-up"
    gate = gates.read(run_dir, g["id"])
    assert gate["flags"] == ["the agent gave up: it needs a budget change"]
    with pytest.raises(common.OpsError, match="may not answer"):
        ops_gates.answer(g["id"], "acknowledged", who="agent")
    with pytest.raises(common.OpsError, match="may not answer"):
        ops_gates.answer(g["id"], "skip", who="chat:home")
    assert same.notify.messages == [f"Phoenix: the agent couldn't fix proj task 1: it needs a budget change. "
                                    f"It needs you (gate {g['id']})."]
    (item,) = handoff.load(run_dir, 1)["items"]
    assert item["state"] == "gave-up" and item["why"] == "it needs a budget change"
    assert outcomes(sent) == [{"gate_id": g["id"], "outcome": "gave-up"}]
    assert [e["data"]["state"] for e in kinds(run_dir, "handoff.ended")] == ["gave-up"]
    with pytest.raises(common.Conflict, match="not handed to the agent"):
        ops.fix("proj", run_dir.name, 1, "retry")
    ops_gates.answer(g["id"], "acknowledged", who="dashboard")           # Alex still can


@pytest.mark.parametrize("action", ["skip", "stop"])
def test_the_agent_still_may_not_skip_or_stop_a_handed_question(tmp_path, runner, sent, same, action):
    run_dir, g = handed_run(tmp_path, runner)
    with pytest.raises(common.OpsError, match="may not answer"):
        ops_gates.answer(g["id"], action, who="agent")
    assert gates.poll(run_dir, g["id"]) is None and handoff.current(run_dir, 1) is not None


def test_api_routes_take_the_real_caller(api, phoenix_env, tmp_path):  # noqa: F811 - fixtures from test_api_server
    rr.make_run(tmp_path)
    base = f"/api/runs/{rr.PROJECT}/{rr.RUN}/handoff"
    status, body = api(f"{base}/fix", "POST", POST_HEADERS, {"task": 1, "action": "retry"})
    assert status == 409 and "Only the Phoenix agent" in body["message"]      # the dashboard is not the agent
    status, body = api(f"{base}/give-up", "POST", POST_HEADERS, {"task": 1, "why": "x"})
    assert status == 409
    assert api(f"{base}/fix", "POST", POST_HEADERS, {"task": "one", "action": "retry"})[0] == 400
    assert api(f"{base}/give-up", "POST", POST_HEADERS, {"task": 1})[0] == 400
