"""The hand-off record (tasks/<n>/handoff.json): thread kept, fixed / failed again / tried twice, outcome lines and the bell."""
import json
import time

import pytest

from helpers.scripted import fail, on
from phoenix9 import bell, events, failmodes, gates, handoff, state, statusreport as sr
from test_handoff import only_gate, project, runner, sent, start  # noqa: F401 - the same worlds as test_handoff

FIXED_LINE = "Phoenix: the agent fixed proj task 1 (it tried again); the build goes on."


def outcomes(calls) -> list[dict]:
    return [json.loads(c["body"]) for c in calls if c["url"].endswith("/handoffs/outcome")]


def handed(calls) -> list[dict]:
    return [c for c in calls if c["url"].endswith("/handoffs")]


def run_events(run_dir, kind) -> list[dict]:
    return [e for e in events.read(run_dir / "events.jsonl") if e["type"] == kind]


def test_the_reply_thread_is_recorded_and_alex_gets_no_line(tmp_path, runner, adapters, sent):
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    record = handoff.load(run_dir, 1)
    assert record["count"] == 1
    (item,) = record["items"]
    assert item["gate"] == g["id"] and item["thread"] == "t-1" and item["state"] == "working"
    assert item["action"] == "" and item["rewrote_checks"] is False and item["started"] and item["ended"] == ""
    assert handoff.current(run_dir, 1) == item and not handoff.rewrite_used(run_dir, 1)
    assert adapters.notify.messages == []
    (ev,) = run_events(run_dir, "handoff.started")
    assert ev["data"] == {"gate": g["id"], "thread": "t-1"}


def test_task_passing_after_the_hand_off_is_fixed_with_one_line_and_the_outcome(tmp_path, runner, adapters, sent):
    on("builder", 1, 1, fail("flaky"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gid = only_gate(run_dir)["id"]
    gates.answer(gid, "acknowledged", who="agent")
    assert runner.drive(run_dir) == "done"
    (item,) = handoff.load(run_dir, 1)["items"]
    assert item["state"] == "fixed" and item["ended"] and handoff.current(run_dir, 1) is None
    assert adapters.notify.messages.count(FIXED_LINE) == 1
    assert not [m for m in adapters.notify.messages if "agent" in m and m != FIXED_LINE]
    assert outcomes(sent) == [{"gate_id": gid, "outcome": "fixed"}]
    assert [e["data"].get("state") for e in run_events(run_dir, "handoff.ended")] == ["fixed"]


def test_a_second_escalation_marks_the_first_failed_again_and_hands_off_again(tmp_path, runner, adapters, sent):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    first = only_gate(run_dir)["id"]
    gates.answer(first, "acknowledged", who="agent")
    assert runner.drive(run_dir) == "waiting"
    record = handoff.load(run_dir, 1)
    assert record["count"] == 2
    assert [i["state"] for i in record["items"]] == ["failed-again", "working"]
    assert record["items"][0]["gate"] == first and record["items"][1]["gate"] == only_gate(run_dir)["id"] != first
    assert outcomes(sent) == [{"gate_id": first, "outcome": "failed-again"}]
    assert len(handed(sent)) == 2
    assert failmodes.HANDOFF_FLAG in only_gate(run_dir)["flags"] and adapters.notify.messages == []


def test_a_third_escalation_goes_to_alex_without_a_hand_off(tmp_path, runner, adapters, sent, monkeypatch):
    monkeypatch.setattr(failmodes, "MAX_ESCALATIONS", 3)     # so the task escalates a third time
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    for _ in range(2):
        gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
        assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    assert g["flags"] == [failmodes.TRIED_TWICE] == ["the agent already tried twice; waiting for you"]
    assert len(handed(sent)) == 2
    record = handoff.load(run_dir, 1)
    assert record["count"] == 2 and [i["state"] for i in record["items"]] == ["failed-again", "failed-again"]
    (told,) = adapters.notify.messages
    assert "needs you" in told and g["id"] in told


def test_the_task_failing_for_good_ends_a_working_hand_off(tmp_path, runner, sent):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    for _ in range(failmodes.MAX_ESCALATIONS):
        runner.drive(run_dir)
        gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    runner.drive(run_dir)
    assert state.load(run_dir)["tasks"]["1"]["status"] == "failed"
    assert handoff.current(run_dir, 1) is None


def test_an_outcome_that_cannot_be_posted_never_breaks_the_runner(tmp_path, runner, adapters, sent):
    on("builder", 1, 1, fail("flaky"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    adapters.agentnext.down = True
    assert runner.drive(run_dir) == "done"
    assert handoff.load(run_dir, 1)["items"][0]["state"] == "fixed"
    assert adapters.notify.messages == [FIXED_LINE]
    assert any(e["data"].get("posted") is False for e in run_events(run_dir, "handoff.ended"))


@pytest.mark.parametrize("status", [500, 404])
def test_post_outcome_is_best_effort(adapters, status):
    adapters.agentnext.status = status
    assert failmodes.post_outcome(adapters.agentnext, "g-1", "gave-up") is False

    class Broken:
        def request(self, *a, **k):
            raise RuntimeError("boom")
    assert failmodes.post_outcome(Broken(), "g-1", "fixed") is False
    assert failmodes.post_outcome(None, "g-1", "fixed") is False


def test_post_outcome_sends_only_the_gate_and_outcome(adapters):
    adapters.agentnext.status = 200
    assert failmodes.post_outcome(adapters.agentnext, "g-1", "failed-again") is True
    (call,) = adapters.agentnext.calls
    assert call["url"] == "http://agent.invalid/handoffs/outcome" and call["timeout"] == failmodes.HANDOFF_TIMEOUT
    assert json.loads(call["body"]) == {"gate_id": "g-1", "outcome": "failed-again"}


def test_why_is_one_scrubbed_line_of_at_most_300_characters(tmp_path):
    run_dir = tmp_path / "run"
    handoff.start(run_dir, 3, "g", "t")
    handoff.finish(run_dir, 3, "gave-up", "line one\nline two " + "x" * 400)
    (item,) = handoff.load(run_dir, 3)["items"]
    assert "\n" not in item["why"] and len(item["why"]) == handoff.WHY_MAX and item["why"].startswith("line one line two")
    with pytest.raises(ValueError):
        handoff.mark(run_dir, 3, action="skip")


def test_mark_and_rewrite_used(tmp_path):
    run_dir = tmp_path / "run"
    assert handoff.mark(run_dir, 1, action="retry") is None
    handoff.start(run_dir, 1, "g", "t")
    handoff.mark(run_dir, 1, action="rewrite-checks", rewrote_checks=True)
    assert handoff.rewrite_used(run_dir, 1) and handoff.current(run_dir, 1)["action"] == "rewrite-checks"


# ---------------------------------------------------------------------- the bell
@pytest.fixture
def quiet(adapters, monkeypatch):
    """Services running and no merge requests: only questions and hand-offs show."""
    adapters.host.script(["systemctl", "is-active"], 0, "active\nactive")
    monkeypatch.setattr(sr, "_open_prs", lambda a: [])
    return adapters


def shown(adapters, now) -> list[dict]:
    return [i for i in bell.items(adapters, now) if i["kind"] in ("agent", "question")]


def test_bell_shows_the_agent_fixing_and_hides_the_question_for_30_minutes(tmp_path, runner, quiet, sent):
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    g = only_gate(run_dir)
    now = time.time()
    (item,) = shown(quiet, now)
    assert item["kind"] == "agent" and item["title"] == "The agent is fixing proj task 1"
    assert item["detail"] == "Open the agent to watch it." and item["thread"] == "t-1"
    assert item["id"] == f"agent:proj:{run_dir.name}.1.0.working"
    assert item["page"] == {"to": "p/proj/build", "params": {"run": run_dir.name}}
    later = shown(quiet, now + 31 * 60)
    assert sorted(i["kind"] for i in later) == ["agent", "question"]
    (late,) = [i for i in later if i["kind"] == "agent"]
    assert late["title"] == "The agent hasn't finished proj task 1" and late["thread"] == "t-1"
    assert late["detail"] == "It needs you: answer the question or open the agent."
    assert [i["id"] for i in later if i["kind"] == "question"] == [f"question:proj:{g['id']}"]
    bell.dismiss(item["id"])
    assert shown(quiet, now) == []                               # dismissed; the late one is a new item
    assert [i["title"] for i in shown(quiet, now + 31 * 60) if i["kind"] == "agent"] == [late["title"]]


def test_bell_shows_fixed_after_the_task_passes(tmp_path, runner, quiet, sent):
    on("builder", 1, 1, fail("flaky"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    runner.drive(run_dir)
    (item,) = shown(quiet, time.time())
    assert item["title"] == "The agent fixed proj task 1" and item["thread"] == "t-1"
    assert item["id"] == f"agent:proj:{run_dir.name}.1.0.fixed"


def test_bell_shows_gave_up_with_the_reason_and_the_question(tmp_path, runner, quiet, sent):
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    handoff.finish(run_dir, 1, "gave-up", "it needs a key only Alex has")
    found = shown(quiet, time.time())
    assert sorted(i["kind"] for i in found) == ["agent", "question"]
    (item,) = [i for i in found if i["kind"] == "agent"]
    assert item["title"] == "The agent gave up on proj task 1: it needs a key only Alex has"
    assert item["thread"] == "t-1" and item["id"].endswith(".1.0.gave-up")


def test_bell_hides_failed_again_and_shows_the_next_hand_off(tmp_path, runner, quiet, sent):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    runner.drive(run_dir)
    (item,) = shown(quiet, time.time())
    assert item["id"] == f"agent:proj:{run_dir.name}.1.1.working"


def test_bell_skips_hand_offs_older_than_seven_days(tmp_path, runner, quiet, sent):
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    handoff.finish(run_dir, 1, "gave-up", "no")
    assert [i["kind"] for i in shown(quiet, time.time() + 8 * 86400)] == ["question"]
