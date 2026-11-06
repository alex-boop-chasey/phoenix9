"""The one place that says what a project is doing now (phoenix9/status.py), and every reader agreeing with it."""
import json

import pytest

from phoenix9 import atomic, gates, paths, runs, state, status
from phoenix9.__main__ import main
from phoenix9.ops import common, gates as gates_ops, projects, runs as runs_ops

SPEC = "# Spec: Add Login\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it works\n\n## Task 2: Second\nGoal: two.\nDone when:\n- two works\n"


@pytest.fixture
def env(phoenix_env, tmp_path, monkeypatch):
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    claude = tmp_path / "claude.json"
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude))
    fakes.host.files[str(claude)] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# demo\n\nAbout demo.\n\n- Profile: python-script\n")
    (folder / "phoenix.toml").write_text('profile = "python-script"\n')
    return {"fakes": fakes, "tmp": tmp_path}


def new_run(env, created=None):
    spec = env["tmp"] / "spec.md"
    spec.write_text(SPEC)
    run_dir = runs.create_run("demo", spec)
    if created:
        state.update(run_dir, lambda s: s.__setitem__("created", created))
    return run_dir


def ask(run_dir, kind="merge"):
    """Open a gate the way the runner does: the run records it waits on it (current.gate)."""
    g = gates.open_gate(run_dir, kind=kind, title="Merge?", why="because")
    state.update(run_dir, lambda s: s["current"].__setitem__("gate", g["id"]))
    return g


def test_no_runs_is_idle(env):
    s = status.project_state("demo")
    assert s["activity"] == "idle" and s["needs_you"] == 0 and s["run"] is None and s["questions"] == []
    assert s["harness"] == "idle" and s["run_text"] == "Idle"


def test_queued_and_running(env):
    run_dir = new_run(env)
    s = status.project_state("demo")
    assert s["activity"] == "run" and s["run"]["status"] == "queued" and s["harness"] == "queued"
    assert s["status_line"] == "Build queued"
    state.update(run_dir, lambda s: (s.__setitem__("status", "running"), s["current"].__setitem__("task", 2)))
    s = status.project_state("demo")
    assert s["run"]["task"] == 2 and s["run"]["tasks"] == 2
    assert s["harness"] == "running task 2 of 2" and s["run_text"] == "Running task 2 of 2"
    assert s["status_line"] == "Building, task 2 of 2"
    assert s["run"]["now"] == "Now: working on task 2 of 2."


def test_waiting_on_an_open_question_needs_you(env):
    run_dir = new_run(env)
    g = ask(run_dir)
    s = status.project_state("demo")
    assert s["activity"] == "need" and s["needs_you"] == 1 and s["questions"] == [g["id"]]
    assert s["run"]["status"] == "waiting" and s["harness"] == "needs you"
    assert s["status_line"] == "1 question waiting" and "waiting for you" in s["run"]["why"]


def test_answered_waiting_run_is_carrying_on(env):
    run_dir = new_run(env)
    g = ask(run_dir)
    gates.answer(g["id"], "approve")
    s = status.project_state("demo")
    assert s["activity"] == "run" and s["needs_you"] == 0
    assert s["run"]["status"] == "running" and s["run"]["carrying_on"] is True
    assert s["run"]["now"] == "Now: answered, Phoenix is carrying on."


@pytest.mark.parametrize("ended", ["stopped", "failed", "done"])
def test_ended_run_with_a_leftover_question_does_not_need_you(env, ended):
    """The bug Alex saw: a stopped run's question still showed as Needs you."""
    run_dir = new_run(env)
    ask(run_dir)
    state.set_status(run_dir, ended)
    s = status.project_state("demo")
    assert s["needs_you"] == 0 and s["run"] is None
    assert s["activity"] == ("fail" if ended == "failed" else "idle")
    assert s["last_build_failed"] is (ended == "failed")


def test_paused_limit_reads_as_a_problem(env):
    run_dir = new_run(env)
    state.set_status(run_dir, "paused-limit")
    s = status.project_state("demo")
    assert s["activity"] == "fail" and s["status_line"] == "Paused at a limit"
    assert s["run_text"] == "Paused (usage limit)"


def test_current_build_prefers_the_run_that_needs_you(env):
    older = new_run(env, created="2026-11-01T10:00:00+00:00")
    g = ask(older)
    new_run(env, created="2026-11-02T10:00:00+00:00")       # queued behind it
    s = status.project_state("demo")
    assert s["run"]["run_id"] == older.name and s["questions"] == [g["id"]]


def test_every_reader_agrees_for_a_stopped_run(env, capsys):
    """Rows, gate list, run status, project list (CLI) and harness all say the same thing."""
    run_dir = new_run(env)
    ask(run_dir)
    state.set_status(run_dir, "stopped")
    row = projects.row("demo")
    assert row["needs_you"] == 0 and row["run"] is None and row["activity"] == "idle"
    assert gates_ops.list_("demo") == []
    assert runs_ops.status(run_dir.name)["gates"] == []
    assert main(["gate", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["project", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["harness"] == "idle"


def test_every_reader_agrees_for_a_waiting_run(env, capsys):
    run_dir = new_run(env)
    g = ask(run_dir)
    row = projects.row("demo")
    assert row["needs_you"] == 1 and row["questions"] == [g["id"]] and row["activity"] == "need"
    assert [x["id"] for x in gates_ops.list_("demo")] == [g["id"]]
    assert [x["id"] for x in runs_ops.status(run_dir.name)["gates"]] == [g["id"]]
    assert main(["project", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["harness"] == "needs you"


def test_rows_and_lists_carry_the_state_fields(env):
    new_run(env)
    row = projects.row("demo")
    for key in ("activity", "status_line", "run_text", "questions", "needs_you", "run", "last_build_failed"):
        assert key in row
    assert {"carrying_on", "why", "now"} <= set(row["run"])
    listed = runs_ops.list_("demo")[0]
    assert listed["status"] == "queued" and listed.get("carrying_on") is not True


def test_no_duplicate_carrying_on_patch_left():
    """The 'answered, carrying on' patch lives only in status.py."""
    from phoenix9.ops import runs as r
    assert not hasattr(r, "with_answers_applied") and not hasattr(r, "carrying_on")
    assert hasattr(status, "seen_run")
