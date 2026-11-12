"""Questions waiting on a person: one message when opened, reminders, and the optional plan auto-approve."""
import pytest

from helpers import scripted
from helpers.scripted import calls, gate, on
from phoenix9 import atomic, events, gatenotify, gates, paths, runs, state, watch
from phoenix9.runner import Runner

import test_attempt_loop as loop

STEPS = {**scripted.STEPS,
         "planner": dict(level="run", phase="start", order=45, needs=["spec"], produces=[],
                         settings={"auto_approve": False})}


def _project():
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    loop.git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    loop.git(code, "add", "-A")
    loop.git(code, "commit", "-q", "-m", "first")
    return paths.projects() / "proj"


@pytest.fixture
def runner(adapters, tmp_path):
    scripted.reset()
    _project()
    yield Runner(adapters, scripted.make_library(tmp_path / "lib", STEPS))
    scripted.reset()


def write_global(text):
    (paths.config()).mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text(text)


def waiting_run(tmp_path, runner, title="Look at the plan", step="builder", **overrides):
    on(step, None, None, gate(title=title, why="SECRET PLAN TEXT"))
    run_dir = loop.start(tmp_path, **overrides)
    assert runner.drive(run_dir) == "waiting"
    return run_dir


def only_gate(run_dir):
    return loop.open_gate(run_dir)


def test_one_message_with_link_when_a_question_opens(tmp_path, runner, adapters):
    write_global('[dashboard]\ndashboard_url = "https://dash.example.com/"\n')
    run_dir = waiting_run(tmp_path, runner, title="Is this ok?   sk-ant-abcdefghijkl1234 please")
    (msg,) = adapters.notify.messages
    assert "proj" in msg and "One task" in msg and "Is this ok?" in msg
    assert "https://dash.example.com/p/proj/build" in msg
    assert "sk-ant-abcdefghijkl1234" not in msg and "SECRET PLAN TEXT" not in msg
    assert gatenotify.read_record(run_dir, only_gate(run_dir)["id"])["reminders"] == 0


def test_no_address_says_where_to_look_and_long_questions_are_cut(tmp_path, runner, adapters):
    waiting_run(tmp_path, runner, title="x" * 500)
    (msg,) = adapters.notify.messages
    assert "http" not in msg and "Needs you" in msg
    assert len(msg) < 400


def test_reminders_every_four_hours_capped_and_not_repeated_after_reload(tmp_path, runner, adapters):
    run_dir = waiting_run(tmp_path, runner)
    clock = adapters.clock
    sent = lambda: len(adapters.notify.messages)           # noqa: E731
    assert sent() == 1
    clock.t += 3.9 * 3600
    assert gatenotify.send_reminders(adapters) == 0
    clock.t += 0.1 * 3600
    assert gatenotify.send_reminders(adapters) == 1 and sent() == 2
    assert "Reminder 1 of 6" in adapters.notify.messages[-1]
    assert gatenotify.send_reminders(adapters) == 0          # same moment, e.g. after a runner restart
    for _ in range(10):
        clock.t += 4 * 3600
        gatenotify.send_reminders(adapters)
    assert sent() == 1 + 6
    assert gatenotify.read_record(run_dir, only_gate(run_dir)["id"])["reminders"] == 6


def test_no_reminder_after_an_answer_or_when_the_run_ends(tmp_path, runner, adapters):
    run_dir = waiting_run(tmp_path, runner)
    gates.answer(only_gate(run_dir)["id"], "approve")
    adapters.clock.t += 5 * 3600
    assert gatenotify.send_reminders(adapters) == 0
    on("builder", None, None, gate(title="again"))
    run_dir2 = waiting_run(tmp_path, runner)
    runner.stop_now(run_dir2)
    adapters.clock.t += 9 * 3600
    assert gatenotify.send_reminders(adapters) == 0


def test_remind_hours_zero_and_custom(tmp_path, runner, adapters):
    waiting_run(tmp_path, runner)
    write_global("[notify]\nremind_hours = 0\n")
    adapters.clock.t += 50 * 3600
    assert gatenotify.send_reminders(adapters) == 0
    write_global("[notify]\nremind_hours = 1\n")
    assert gatenotify.send_reminders(adapters) == 1
    adapters.clock.t += 1.1 * 3600
    assert gatenotify.send_reminders(adapters) == 1


def test_watch_loop_sends_reminders_once_a_minute(tmp_path, runner, adapters):
    waiting_run(tmp_path, runner)
    memory = watch.Memory()
    adapters.clock.t += 4 * 3600
    watch.check_gate_reminders(adapters, memory)
    watch.check_gate_reminders(adapters, memory)
    assert len(adapters.notify.messages) == 2


def test_escalation_gate_is_told_once_by_failmodes_then_reminded(tmp_path, runner, adapters):
    loop.on("builder", 1, None, loop.fail("broke"))
    run_dir = loop.start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert len(adapters.notify.messages) == 1
    adapters.clock.t += 4 * 3600
    assert gatenotify.send_reminders(adapters) == 1


# ---- auto-approve
def plan_run(tmp_path, runner, kind="plan", auto=None, step="planner"):
    on(step, None, None, gate(kind=kind, title="Approve the plan"))
    overrides = {"steps": {"planner": {"auto_approve": auto}}} if auto is not None else {}
    run_dir = loop.start(tmp_path, **overrides)
    return run_dir, runner.drive(run_dir)


def test_plan_is_not_auto_approved_by_default(tmp_path, runner, adapters):
    run_dir, outcome = plan_run(tmp_path, runner)
    assert outcome == "waiting" and gates.poll(run_dir, only_gate(run_dir)["id"]) is None


def test_plan_auto_approved_when_the_setting_is_on(tmp_path, runner, adapters):
    on("planner", None, None, gate(kind="plan", title="Approve the plan"))
    run_dir = loop.start(tmp_path, steps={"planner": {"auto_approve": True}})
    assert runner.drive(run_dir) == "done"
    (g,) = gates.run_gates(run_dir)
    assert g["answer"]["who"] == "setting" and g["answer"]["action"] == "approve"
    assert "automatically" in g["answer"]["note"]
    answered = [e for e in events.read(run_dir / "events.jsonl") if e["type"] == "gate.answered"]
    assert answered[0]["data"]["who"] == "setting"
    assert any("plan approved automatically (project setting)" in m for m in adapters.notify.messages)
    assert len(adapters.notify.messages) == 1               # the 'waiting' message is not sent as well


@pytest.mark.parametrize("kind,step", [("merge", "planner"), ("step", "planner"), ("plan", "builder"),
                                       ("escalation", "planner"), ("deploy", "planner")])
def test_auto_approve_never_answers_any_other_question(tmp_path, runner, kind, step):
    on(step, None, None, gate(kind=kind, title="Question"))
    run_dir = loop.start(tmp_path, steps={"planner": {"auto_approve": True}})
    assert runner.drive(run_dir) == "waiting"
    assert gates.poll(run_dir, only_gate(run_dir)["id"]) is None


def test_auto_approve_never_answers_safety_file_human_or_spending_questions(tmp_path, runner, adapters):
    on("builder", None, None, gate(kind="step", title="Safety files changed", flags=["safety files"]))
    run_dir = loop.start(tmp_path, steps={"planner": {"auto_approve": True}}, budget_usd=0.01)
    assert runner.drive(run_dir) == "waiting"
    assert gates.poll(run_dir, only_gate(run_dir)["id"]) is None
    human = loop.start(tmp_path, loop.HUMAN, steps={"planner": {"auto_approve": True}})
    assert runner.drive(human) == "waiting"
    assert gates.poll(human, loop.open_gate(human)["id"]) is None


def test_budget_gate_is_not_auto_approved(tmp_path, runner, adapters):
    on("builder", None, None, scripted.StepResult("pass", produces={"diff": "x"}))
    run_dir = loop.start(tmp_path, steps={"planner": {"auto_approve": True}}, budget_usd=1.0)
    state.update(run_dir, lambda s: s.setdefault("usage", {}).update(cost_usd=2.0, sessions=1))
    assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    assert g["kind"] == "budget" and gates.poll(run_dir, g["id"]) is None


def test_the_agent_may_not_switch_auto_approve_on():
    from phoenix9.ops import settings as ops_settings
    assert ops_settings.is_safety_key("steps.planner.auto_approve")
