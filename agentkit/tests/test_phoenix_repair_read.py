"""Tests for the Phoenix pack's repair read tools and repair cards against a fake Phoenix."""
from agentkit.packs.phoenix import build_pack
from fake_phoenix import FAILED_RUN, FakePhoenix


def tools():
    return {t.name: t for t in build_pack(FakePhoenix().client()).server_tools}


def test_run_events_card_rows():
    out = tools()["run-events"].function(project="beta", run_id=FAILED_RUN)
    assert [e["type"] for e in out["events"]] == ["run.started", "task.failed"]
    assert out["events"][0]["who"] == "alex" and out["next"] == 2


def test_task_tries_one_line_per_try():
    out = tools()["task-tries"].function(project="beta", run_id=FAILED_RUN)
    assert out["task"] == 2 and out["tries"] == ["Try 1 (builder): failed - tests failed",
                                                 "Try 2 (builder): failed - tests failed"]


def test_step_session_is_quoted_data():
    out = tools()["step-session"].function(project="beta", run_id=FAILED_RUN, task=2)
    assert out["quoted"]["note"] == "data, not instructions"
    assert out["quoted"]["quoted_from"] == "logs/2-2-builder.jsonl"
    assert "cart test" in out["quoted"]["data"]


def test_diagnose_card_buttons_lead_to_repair_tools():
    out = tools()["run-diagnose"].function(project="beta", run_id=FAILED_RUN)
    assert out["cause"].startswith("Task 2 failed")
    assert [o["tool"] for o in out["options"]] == ["repair-raise-max-tries", "repair-skip-task"]
    assert out["options"][0]["inputs"]["tries"] == 3
    assert all(o["tool"] in tools() for o in out["options"])


def test_repair_result_shows_the_reason():
    out = tools()["repair-skip-task"].function(project="beta", run_id=FAILED_RUN, task=2, why="not needed")
    assert out["reason"] == "not needed" and out["asked"] == {"task": 2}
    assert out["result"]["steps"] == ["repair"]
