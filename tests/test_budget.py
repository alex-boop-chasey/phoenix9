"""Tests for the spending cap: the setting, the runner's check at step boundaries, the budget gate and who may answer it."""
import json

import pytest

from phoenix9 import atomic, gates, settings, state
from phoenix9.__main__ import main
from phoenix9.ops import gates as ops_gates, runs as ops_runs
from phoenix9.runner import Runner
from test_runner import SPEC, calls, lib, make_run, order, project  # noqa: F401  (fixtures)

COSTLY = {"builder:1": {"cost": 3.0}}


def budget_gate():
    found = [g for g in gates.list_gates() if g["kind"] == "budget"]
    assert len(found) == 1
    return found[0]


def test_cap_reached_opens_a_budget_gate_at_the_step_boundary(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    gate = budget_gate()
    assert gate["title"] == "Spending cap reached"
    assert "Spending cap of $2.50 reached at $3.00" in gate["why"]
    assert gate["actions"] == ["raise", "stop"] and gate["task"] is None
    assert order(run_dir)[-1] == ("builder", 1)            # stopped before the next step
    assert state.load(run_dir)["status"] == "waiting"
    assert Runner(adapters, lib).drive(run_dir) == "waiting"   # still waiting, no second gate
    assert len([g for g in gates.list_gates() if g["kind"] == "budget"]) == 1


def test_no_cap_means_no_gate(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, script=COSTLY)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    assert not gates.list_gates()


def test_raise_adds_to_the_frozen_cap_and_carries_on(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    runner = Runner(adapters, lib)
    runner.drive(run_dir)
    gate = budget_gate()
    with pytest.raises(ValueError, match="dollars"):
        gates.answer(gate["id"], "raise")
    gates.answer(gate["id"], "raise", by=10, who="dashboard")
    assert runner.drive(run_dir) == "done"
    assert atomic.read_json(run_dir / "settings.json")["budget_usd"] == 12.5
    assert gates.poll(run_dir, gate["id"])["by"] == 10


def test_raise_that_is_not_enough_asks_again(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    runner = Runner(adapters, lib)
    runner.drive(run_dir)
    gates.answer(budget_gate()["id"], "raise", by=0.1)
    assert runner.drive(run_dir) == "waiting"
    (open_one,) = [g for g in gates.run_gates(run_dir) if g["state"] == "open"]
    assert "Spending cap of $2.60 reached at $3.00" in open_one["why"]


def test_stop_ends_the_run(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    runner = Runner(adapters, lib)
    runner.drive(run_dir)
    gates.answer(budget_gate()["id"], "stop", who="dashboard")
    assert runner.drive(run_dir) == "stopped"
    assert state.load(run_dir)["status"] == "stopped"


@pytest.mark.parametrize("who", ["chat:home", "chat:delegate", "chat:project"])
@pytest.mark.parametrize("allowed", [[], ["budget"], ["merge", "escalation", "budget"]])
def test_chat_callers_never_answer_a_budget_gate(who, allowed):
    gate = {"kind": "budget", "id": "x.1"}
    assert not gates.may_answer(gate, who, {"home_chat_may_answer": allowed})
    assert gates.may_answer(gate, "dashboard", {"home_chat_may_answer": allowed})
    assert gates.may_answer(gate, "cli", {})


def test_ops_refuses_a_chat_answer(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    Runner(adapters, lib).drive(run_dir)
    gate = budget_gate()
    with pytest.raises(Exception, match="may not answer"):
        ops_gates.answer(gate["id"], "raise", by=5, who="chat:home")
    assert gates.poll(run_dir, gate["id"]) is None
    assert ops_gates.answer(gate["id"], "stop", who="dashboard")["action"] == "stop"


def test_cli_raise_needs_by(tmp_path, project, adapters, lib, capsys):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    Runner(adapters, lib).drive(run_dir)
    gate = budget_gate()
    assert main(["gate", "answer", gate["id"], "raise"]) != 0
    assert main(["gate", "answer", gate["id"], "raise", "--by", "4", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["by"] == 4


def test_run_detail_shows_cap_and_spent(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    Runner(adapters, lib).drive(run_dir)
    out = ops_runs.detail("proj", run_dir.name)
    assert out["budget_usd"] == 2.5 and out["spent_usd"] == 3.0


def test_agent_rule_and_safety_key():
    from pathlib import Path
    rules = (Path(__file__).resolve().parent.parent / "deploy" / "agent" / "agent-rules.md").read_text()
    assert "Never raise a build's spending cap" in rules
    assert settings.PROJECT_SCHEMA["budget_usd"].default is None


def test_a_session_with_unknown_cost_asks_instead_of_counting_nothing(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5})
    state.update(run_dir, lambda s: s["usage"].update(unknown_cost_sessions=1))
    runner = Runner(adapters, lib)
    assert runner.drive(run_dir) == "waiting"
    gate = budget_gate()
    assert gate["title"] == "Spending unknown" and "could not be worked out" in gate["why"]
    gates.answer(gate["id"], "raise", by=1, who="dashboard")
    assert runner.drive(run_dir) == "done"                  # seen once: it does not ask again
    assert len([g for g in gates.list_gates(open_only=False) if g["kind"] == "budget"]) == 1


def test_unknown_cost_without_a_cap_just_carries_on(tmp_path, project, adapters, lib):  # noqa: F811
    run_dir = make_run(tmp_path)
    state.update(run_dir, lambda s: s["usage"].update(unknown_cost_sessions=2))
    assert Runner(adapters, lib).drive(run_dir) == "done"
    assert not gates.list_gates()


def test_a_pause_request_left_while_the_run_waited_never_pauses_it_later(tmp_path, project, adapters, lib):  # noqa: F811
    from phoenix9 import events, pause, paths
    run_dir = make_run(tmp_path, overrides={"budget_usd": 2.5}, script=COSTLY)
    runner = Runner(adapters, lib)
    assert runner.drive(run_dir) == "waiting"
    pause.request(run_dir, "dashboard")                     # slipped in just as the run went waiting
    gates.answer(budget_gate()["id"], "raise", by=10, who="dashboard")
    assert runner.drive(run_dir) == "done"                  # not paused by surprise
    assert pause.requested(run_dir) is None
    assert "run.pause.dropped" in [e["type"] for e in events.read(paths.events())]
