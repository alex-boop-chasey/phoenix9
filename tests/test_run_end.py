"""Every way a run ends closes its open questions (A3), and the runner's start-up catch-up."""
import json

import pytest

from fakes import fake_adapters
from phoenix9 import events, gates, paths, runs, state, summary, watch
from phoenix9.ops import common, gates as gates_ops, logs as logs_ops, runs as ops_runs

SPEC = "# Spec: Demo\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it works fine\n"


@pytest.fixture
def ad(tmp_path, monkeypatch):
    fakes = fake_adapters(tmp_path)
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    (paths.projects() / "alpha" / "notes").mkdir(parents=True)
    return fakes


def make_run(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text(SPEC)
    return runs.create_run("alpha", p)


def ask(run_dir, task=1):
    g = gates.open_gate(run_dir, kind="escalation", title="Task 1 needs you", why="tried", task=task)
    state.update(run_dir, lambda s: (s["current"].__setitem__("gate", g["id"]), s["tasks"]["1"].__setitem__("gate", g["id"])))
    return g


def answer_of(run_dir, gate_id):
    return json.loads((run_dir / "gates" / f"{gate_id}.answer.json").read_text())


def test_close_questions_writes_closed_answers_and_events(tmp_path):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    assert gates.close_questions(run_dir, "run stopped", who="cli") == [g["id"]]
    a = answer_of(run_dir, g["id"])
    assert a["action"] == "closed" and a["reason"] == "run stopped" and a["who"] == "cli" and a["at"]
    last = events.read(run_dir / "events.jsonl")[-1]
    assert last["type"] == "gate.answered" and last["data"]["action"] == "closed"
    assert last["data"]["reason"] == "run stopped"
    assert gates.close_questions(run_dir, "run stopped") == []          # nothing left to close
    assert gates.run_gates(run_dir)[0]["state"] == "closed"


def test_history_shows_closed_reason(tmp_path, ad):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    gates.close_questions(run_dir, "run stopped", who="cli")
    text = logs_ops.read("alpha", f"{run_dir.name}/gates/{g['id']}.json")["text"]
    assert "closed: run stopped" in text
    assert "Task 1: closed: run stopped" in summary.markdown(summary.facts(run_dir))


def test_answering_a_closed_question_is_refused(tmp_path, ad):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    gates.close_questions(run_dir, "run stopped", who="cli")
    with pytest.raises(gates.NotOpen, match="closed"):
        gates.answer(g["id"], "skip")
    with pytest.raises(common.Conflict, match="closed"):
        gates_ops.answer(g["id"], "skip")


def test_answering_a_question_of_an_ended_run_is_refused(tmp_path, ad):
    """An old run stopped before this fix: its gate has no answer file, but the run is over."""
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    state.set_status(run_dir, "stopped")
    with pytest.raises(common.Conflict, match="already stopped"):
        gates_ops.answer(g["id"], "skip")
    assert not (run_dir / "gates" / f"{g['id']}.answer.json").exists()


def test_answering_a_question_the_run_moved_past_is_refused(tmp_path, ad):
    run_dir = make_run(tmp_path)
    old = ask(run_dir)
    ask(run_dir)          # a newer question replaces it as current.gate
    with pytest.raises(common.Conflict, match="not waiting on"):
        gates_ops.answer(old["id"], "skip")


def test_ops_stop_closes_questions(tmp_path, ad):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    ops_runs.stop(run_dir.name)
    assert answer_of(run_dir, g["id"])["reason"] == "run stopped"


def test_watch_fail_closes_questions(tmp_path, ad):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    watch._fail(ad, state.load(run_dir), "boom")
    assert state.load(run_dir)["status"] == "failed"
    assert answer_of(run_dir, g["id"])["reason"] == "run failed"


def test_startup_catch_up_closes_questions_of_ended_runs(tmp_path, ad):
    """The two live cases: runs stopped while waiting, whose questions were left open by the old code."""
    stopped, failed, going = make_run(tmp_path), make_run(tmp_path), make_run(tmp_path)
    gs, gf, gg = ask(stopped), ask(failed), ask(going)
    state.set_status(stopped, "stopped")
    state.set_status(failed, "failed")
    closed = watch.catch_up()
    assert sorted(closed) == sorted([gs["id"], gf["id"]])
    assert answer_of(stopped, gs["id"]) | {"at": ""} == {"action": "closed", "reason": "run stopped", "who": "phoenix",
                                                         "note": "", "at": ""}
    assert answer_of(failed, gf["id"])["reason"] == "run failed"
    assert not (going / "gates" / f"{gg['id']}.answer.json").exists()
    assert [e for e in events.read(paths.events()) if (e.get("data") or {}).get("action") == "closed"].__len__() == 2
    assert watch.catch_up() == []                                    # nothing twice


def test_watch_forever_runs_the_catch_up_first(tmp_path, ad, monkeypatch):
    run_dir = make_run(tmp_path)
    g = ask(run_dir)
    state.set_status(run_dir, "stopped")

    class Stop(Exception):
        pass

    def stop(*a):
        raise Stop
    monkeypatch.setattr(watch, "watch_once", stop)
    with pytest.raises(Stop):
        watch.watch_forever(ad, object())
    assert answer_of(run_dir, g["id"])["action"] == "closed"


# ---- the runner's own ends ----

@pytest.fixture
def scripted_runner(tmp_path, ad):
    import subprocess
    from helpers import scripted
    from phoenix9.runner import Runner
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", "-C", str(code), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True)
    scripted.reset()
    yield Runner(ad, scripted.make_library(tmp_path / "lib"))
    scripted.reset()


def start(tmp_path, **overrides):
    p = tmp_path / "spec.md"
    p.write_text(SPEC)
    return runs.create_run("proj", p, overrides or None)


def test_run_done_closes_a_leftover_question(tmp_path, scripted_runner):
    run_dir = start(tmp_path)
    stray = gates.open_gate(run_dir, kind="step", title="Old", why="left over")
    state.set_status(run_dir, "queued")
    assert scripted_runner.drive(run_dir) == "done"
    assert answer_of(run_dir, stray["id"]) | {"at": ""} == {"action": "closed", "reason": "run done", "who": "phoenix",
                                                            "note": "", "at": ""}


def test_stop_answer_ends_the_run_with_no_open_question(tmp_path, scripted_runner):
    from helpers.scripted import fail, on
    on("builder", 1, 1, fail("broke"))
    run_dir = start(tmp_path, max_tries=1, on_failure="pause")
    assert scripted_runner.drive(run_dir) == "waiting"
    (g,) = gates.list_gates("proj")
    gates.answer(g["id"], "stop")
    assert scripted_runner.drive(run_dir) == "stopped"
    assert gates.list_gates() == []
    assert gates.run_gates(run_dir)[0]["state"] == "answered"
