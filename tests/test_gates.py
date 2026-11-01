"""Tests for opening, listing, answering and polling gates."""
import pytest

from phoenix9 import events, gates, paths, runs, state

SPEC = """# Spec: Demo

## Task 1: First
Goal: do it.
Done when:
- it works fine
"""


def make_run(tmp_path, project="alpha"):
    p = tmp_path / f"spec-{project}.md"
    p.write_text(SPEC)
    return runs.create_run(project, p)


def open_one(folder, **kw):
    args = dict(kind="merge", title="Merge?", why="because")
    args.update(kw)
    return gates.open_gate(folder, **args)


def test_ids_increase_per_run(tmp_path):
    folder = make_run(tmp_path)
    a, b = open_one(folder), open_one(folder)
    run_id = state.load(folder)["run_id"]
    assert (a["id"], b["id"]) == (f"{run_id}.1", f"{run_id}.2")


def test_default_actions_and_state(tmp_path):
    folder = make_run(tmp_path)
    assert open_one(folder, task=1)["actions"] == ["approve", "back", "skip", "stop"]
    esc = open_one(folder, kind="escalation")
    assert esc["actions"] == ["acknowledged", "skip", "stop"]
    s = state.load(folder)
    assert s["status"] == "waiting" and s["tasks"]["1"]["status"] == "waiting"
    assert events.read(folder / "events.jsonl")[-1]["type"] == "gate.opened"
    with pytest.raises(ValueError):
        open_one(folder, kind="nope")


def test_answer_writes_file_and_event(tmp_path):
    folder = make_run(tmp_path)
    g = open_one(folder)
    res = gates.answer(g["id"], "approve", who="dashboard")
    assert res["action"] == "approve" and res["who"] == "dashboard"
    assert gates.poll(folder, g["id"])["action"] == "approve"
    assert events.read(folder / "events.jsonl")[-1]["type"] == "gate.answered"
    assert state.load(folder)["status"] == "waiting"


def test_double_answer_refused(tmp_path):
    folder = make_run(tmp_path)
    g = open_one(folder)
    gates.answer(g["id"], "skip")
    with pytest.raises(ValueError, match="already"):
        gates.answer(g["id"], "stop")
    with pytest.raises(ValueError, match="no such"):
        gates.answer("nope.1", "stop")


def test_bad_action_and_back_needs_note(tmp_path):
    folder = make_run(tmp_path)
    g = open_one(folder, kind="escalation")
    with pytest.raises(ValueError, match="not allowed"):
        gates.answer(g["id"], "approve")
    g2 = open_one(folder)
    with pytest.raises(ValueError, match="note"):
        gates.answer(g2["id"], "back")
    assert gates.poll(folder, g2["id"]) is None
    gates.answer(g2["id"], "back", note="fix the colour")


def test_list_filters(tmp_path):
    fa, fb = make_run(tmp_path, "alpha"), make_run(tmp_path, "beta")
    ga, gb = open_one(fa), open_one(fb)
    assert {g["id"] for g in gates.list_gates()} == {ga["id"], gb["id"]}
    assert [g["id"] for g in gates.list_gates("beta")] == [gb["id"]]
    gates.answer(ga["id"], "approve")
    assert [g["id"] for g in gates.list_gates()] == [gb["id"]]
    assert {g["id"] for g in gates.list_gates(open_only=False)} == {ga["id"], gb["id"]}
    assert gates.list_gates("nobody") == []


def test_chat_may_answer(tmp_path):
    folder = make_run(tmp_path)
    g = open_one(folder)
    assert not gates.may_answer(g, "chat:home", {})
    assert not gates.may_answer(g, "chat:home", {"home_chat_may_answer": ["plan"]})
    assert gates.may_answer(g, "chat:home", {"home_chat_may_answer": ["merge"]})
    assert gates.may_answer(g, "dashboard", {})


def test_poll_none_then_answer(tmp_path):
    folder = make_run(tmp_path)
    g = open_one(folder)
    assert gates.poll(folder, g["id"]) is None
    gates.answer(g["id"], "approve")
    assert gates.poll(folder, g["id"])["action"] == "approve"
