"""The attempt loop: retries, failure modes, gates and resuming (phase 2 prologue acceptance tests).

Every test uses the scripted step library (tests/helpers/scripted.py), the fake adapters and a temp
project whose code/ is a real git repo, so the run gets a real worktree.
"""
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import calls, fail, gate, on
from phoenix9 import atomic, chat, claude, failmodes, gates, paths, runs, state, watch
from phoenix9.ops import common
from phoenix9.ops import runs as ops_runs
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult, UsageLimit

ONE = """# Spec: One task

## Task 1: Only thing
Goal: make it work.
Done when:
- it works
"""

THREE = """# Spec: Three tasks

## Task 1: First
Goal: one.
Done when:
- one works

## Task 2: Second
Goal: two.
Depends on: 1
Done when:
- two works

## Task 3: Third
Goal: three.
Depends on: none
Done when:
- three works
"""

HUMAN = THREE.replace("Goal: one.\n", "Goal: buy the domain.\nFor you: yes\n")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path):
    """A project whose code/ is a real git repo with one commit on main."""
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return paths.projects() / "proj"


@pytest.fixture
def lib(tmp_path):
    """The scripted library, with a clean script for this test."""
    scripted.reset()
    yield scripted.make_library(tmp_path / "lib")
    scripted.reset()


@pytest.fixture
def runner(adapters, lib, project):
    return Runner(adapters, lib)


def start(tmp_path, spec=ONE, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(spec)
    return runs.create_run("proj", f, overrides or None)


def task(run_dir, n=1) -> dict:
    return state.load(run_dir)["tasks"][str(n)]


def worktree(run_dir) -> Path:
    st = state.load(run_dir)
    return paths.work(st["project"], st["run_id"])


def open_gate(run_dir) -> dict:
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    return g


def attempts(step, n=1):
    return [c["attempt"] for c in calls(step, n)]


# 1
def test_pass_first_attempt(tmp_path, runner):
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    t = task(run_dir)
    assert t["status"] == "passed" and t["tries"] == 1
    assert state.load(run_dir)["status"] == "done"
    assert failmodes.attempt_result(run_dir, 1, 1)["status"] == "passed"


# 2
def test_retry_feeds_reasons_forward(tmp_path, runner):
    on("builder", 1, 1, fail("A"))
    on("builder", 1, 2, fail("B"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert [c["failures"] for c in calls("builder", 1)] == [[], ["A"], ["A", "B"]]
    assert attempts("builder") == [1, 2, 3]
    assert task(run_dir)["status"] == "passed" and task(run_dir)["tries"] == 3


# 3
def test_failed_attempt_is_thrown_away(tmp_path, runner, adapters):
    seen = {}

    def write_checks(ctx):
        (ctx.worktree / "check_one.txt").write_text("check\n")
        adapters.git.commit(ctx.worktree, "Checks for task 1", {"Phoenix-Task": "1"})
        return StepResult("pass", produces={"checks": ["check_one.txt"]})

    def build(ctx):
        seen[ctx.attempt] = {"junk": (ctx.worktree / "junk.txt").exists(),
                             "checks": (ctx.worktree / "check_one.txt").exists()}
        (ctx.worktree / "junk.txt").write_text("half-done work\n")
        (ctx.worktree / "README.md").write_text("changed\n")
        return StepResult("pass")

    on("checks", 1, None, write_checks)
    on("builder", 1, None, build)
    on("acceptance", 1, 1, fail("checks failed"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert seen[1] == {"junk": False, "checks": True}
    assert seen[2] == {"junk": False, "checks": True}       # attempt 1's junk is gone, the checks stay
    log = git(worktree(run_dir), "log", "--format=%s")
    assert "Checks for task 1" in log


# 4
def test_once_steps_run_first_attempt_only(tmp_path, runner):
    on("builder", 1, 1, fail("A"))
    on("builder", 1, 2, fail("B"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert attempts("checks") == [1]
    assert attempts("builder") == [1, 2, 3]
    assert task(run_dir)["attempt_base"] == git(worktree(run_dir), "rev-parse", "HEAD").strip()


# 5
def test_two_identical_failures_escalate(tmp_path, runner):
    on("builder", 1, None, fail("the same thing broke"))
    run_dir = start(tmp_path, max_tries=5, on_failure="continue")
    assert runner.drive(run_dir) == "failed"
    assert attempts("builder") == [1, 2]
    assert task(run_dir)["status"] == "failed"
    assert task(run_dir)["flagged"] == "the same thing broke"


# 6
def test_spec_problem_escalates_at_once(tmp_path, runner, adapters):
    on("builder", 1, None, fail("SPEC_PROBLEM: task 1 asks for two opposite things"))
    run_dir = start(tmp_path, max_tries=5)
    assert runner.drive(run_dir) == "waiting"
    assert attempts("builder") == [1]
    g = open_gate(run_dir)
    assert g["kind"] == "escalation" and "SPEC_PROBLEM" in g["why"]


# 7
def test_continue_skips_dependents_and_flags(tmp_path, runner):
    on("builder", 1, 1, fail("first reason"))
    on("builder", 1, 2, fail("second reason"))
    run_dir = start(tmp_path, THREE, max_tries=2, on_failure="continue")
    assert runner.drive(run_dir) == "failed"
    st = state.load(run_dir)
    t1, t2, t3 = (st["tasks"][n] for n in "123")
    assert t1["status"] == "failed" and t1["flagged"] == "second reason"
    assert t2["status"] == "skipped" and t2["note"] == "depends on task 1, which failed"
    assert t3["status"] == "passed"
    assert calls("builder", 2) == [] and len(calls("builder", 3)) == 1
    assert calls("summary") and calls("notify")
    assert st["status"] == "failed"


# 8
def test_pause_opens_escalation_gate(tmp_path, runner, adapters):
    on("builder", 1, None, fail("it broke"))
    run_dir = start(tmp_path, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    g = open_gate(run_dir)
    assert g["kind"] == "escalation" and g["actions"] == ["acknowledged", "skip", "stop"]
    assert g["title"] == "Task 1 needs you" and g["why"] == "it broke"
    assert g["links"] and "attempt-1" in g["links"][0]["url"]
    st = state.load(run_dir)
    assert st["status"] == "waiting" and st["tasks"]["1"]["status"] == "waiting"
    assert st["current"]["gate"] == g["id"] == st["tasks"]["1"]["gate"]
    assert len(adapters.notify.messages) == 1 and g["id"] in adapters.notify.messages[0]
    assert calls("summary") == []


# 9
def test_pause_ack_reruns_once_and_passes(tmp_path, runner):
    on("builder", 1, 1, fail("missing config"))
    run_dir = start(tmp_path, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "acknowledged", note="added the config")
    assert runner.drive(run_dir) == "done"
    assert attempts("builder") == [1, 2]
    assert calls("builder")[1]["failures"] == ["missing config", "Note from cli: added the config"]
    t = task(run_dir)
    assert t["status"] == "passed" and t["escalations"] == 1 and t["gate"] is None


# 10
def test_pause_second_failure_follows_mode_once_more_then_fails(tmp_path, runner, adapters):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path, THREE, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert runner.drive(run_dir) == "waiting"                  # second escalation
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert runner.drive(run_dir) == "failed"
    assert len(gates.list_gates(open_only=False)) == 2       # no third gate
    assert attempts("builder", 1) == [1, 2, 3]
    st = state.load(run_dir)
    assert st["tasks"]["1"]["status"] == "failed" and st["tasks"]["1"]["escalations"] == 2
    assert st["tasks"]["2"]["status"] == "skipped" and st["tasks"]["3"]["status"] == "passed"
    assert len(adapters.notify.messages) == 2


# 11
def test_outside_fix_committed_before_rerun(tmp_path, runner):
    seen = []
    on("builder", 1, 1, fail("no config file"))
    on("builder", 1, 2, lambda ctx: seen.append((ctx.worktree / "config.ini").exists()) or StepResult("pass"))
    run_dir = start(tmp_path, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    work = worktree(run_dir)
    (work / "config.ini").write_text("[x]\n")
    (work / ".env").write_text("SECRET=1\n")
    gates.answer(open_gate(run_dir)["id"], "acknowledged", note="wrote config.ini")
    assert runner.drive(run_dir) == "done"
    assert seen == [True]
    sha = task(run_dir)["attempt_base"]
    message = git(work, "log", "-1", "--format=%B", sha)
    assert message.startswith("Outside fix before retry of task 1")
    assert "Phoenix-Fix-By: cli" in message and f"Phoenix-Run: {run_dir.name}" in message
    files = git(work, "show", "--name-only", "--format=", sha).split()
    assert files == ["config.ini"]
    assert not (work / ".env").exists()                                   # moved out of the worktree
    assert (run_dir / "tasks" / "1" / "outside-env" / ".env").read_text() == "SECRET=1\n"
    line = "env file .env was moved out of the worktree; keys belong in Phoenix secrets"
    assert line in task(run_dir)["failures"]
    assert any(line in m for m in runner.adapters.notify.messages)


# 12
def test_delegate_calls_chat_adapter(tmp_path, runner, adapters):
    on("builder", 1, 1, fail("missing dependency"))
    run_dir = start(tmp_path, max_tries=1, on_failure="delegate")
    assert runner.drive(run_dir) == "done"
    assert attempts("builder") == [1, 2]
    (g,) = gates.list_gates(open_only=False)
    assert "delegated to project chat" in g["flags"]
    assert gates.poll(run_dir, g["id"])["who"] == "chat:delegate"
    assert adapters.notify.messages == []
    (args, _), = adapters.chat.calls
    project, project_dir, gate_id, prompt, log_path = args
    assert project == "proj" and Path(project_dir) == paths.projects() / "proj" and gate_id == g["id"]
    assert g["id"] in prompt and str(worktree(run_dir)) in prompt and "missing dependency" in prompt
    assert "{{" not in prompt


# 13
def test_delegate_gives_up_falls_back_to_pause(tmp_path, runner, adapters):
    adapters.chat.mode = "exit"
    adapters.chat.log = [f"line {i}" for i in range(30)] + ["DELEGATE GAVE UP: needs a paid account"]
    on("builder", 1, 1, fail("payment needed"))
    run_dir = start(tmp_path, max_tries=1, on_failure="delegate")
    assert runner.drive(run_dir) == "waiting"
    assert len(adapters.notify.messages) == 1
    assert "could not fix task 1" in adapters.notify.messages[0]
    assert "DELEGATE GAVE UP" in adapters.notify.messages[0] and "line 5\n" not in adapters.notify.messages[0]
    assert runner.drive(run_dir) == "waiting"
    watch.watch_once(adapters, runner)
    assert len(adapters.notify.messages) == 1
    g = open_gate(run_dir)
    gates.answer(g["id"], "acknowledged", who="cli")
    assert runner.drive(run_dir) == "done"
    assert attempts("builder") == [1, 2] and len(adapters.chat.calls) == 1


# 14
def test_delegate_timeout_notifies(tmp_path, runner, adapters):
    adapters.chat.mode = "run"
    on("builder", 1, 1, fail("flaky network"))
    run_dir = start(tmp_path, max_tries=1, on_failure="delegate")
    assert runner.drive(run_dir) == "waiting"
    assert adapters.notify.messages == []
    adapters.clock.t += (failmodes.DELEGATE_TIMEOUT_MIN - 1) * 60
    watch.watch_once(adapters, runner)
    assert adapters.notify.messages == []
    adapters.clock.t += 60
    watch.watch_once(adapters, runner)
    watch.watch_once(adapters, runner)
    assert len(adapters.notify.messages) == 1 and "waiting for you" in adapters.notify.messages[0]
    assert state.load(run_dir)["status"] == "waiting"


# 15
def test_delegate_cannot_start_falls_back_to_pause(tmp_path, runner, adapters):
    adapters.chat.mode = "fail"
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path, max_tries=1, on_failure="delegate")
    assert runner.drive(run_dir) == "waiting"
    assert len(adapters.notify.messages) == 1
    assert "could not be started" in adapters.notify.messages[0]
    assert runner.drive(run_dir) == "waiting"
    assert len(adapters.notify.messages) == 1
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert runner.drive(run_dir) == "done"


# 16
@pytest.mark.parametrize("action", ["approve", "skip", "stop"])
def test_human_task_gate_approve_skip_stop(tmp_path, runner, action):
    run_dir = start(tmp_path, HUMAN)
    assert runner.drive(run_dir) == "waiting"
    g = open_gate(run_dir)
    assert g["kind"] == "human-task" and g["actions"] == ["approve", "skip", "stop"]
    assert "buy the domain" in g["why"] and "one works" in g["why"]
    assert calls("builder", 1) == []                         # no task steps for a human task
    gates.answer(g["id"], action)
    final = runner.drive(run_dir)
    st = state.load(run_dir)
    statuses = [st["tasks"][n]["status"] for n in "123"]
    if action == "approve":
        assert final == "done" and statuses == ["passed", "passed", "passed"]
    elif action == "skip":
        assert final == "done" and statuses == ["skipped", "skipped", "passed"]
        assert st["tasks"]["2"]["note"] == "depends on task 1, which was skipped"
    else:
        assert final == "stopped" and st["status"] == "stopped"
        assert calls("builder") == []
        assert calls("notify") and calls("summary") == []   # only after_stop finish steps run


# 17
def test_step_gate_back_recalls_step_with_note(tmp_path, runner):
    on("pick-up", None, None, gate(title="Look at the plan"),
       lambda ctx: gate(title="Look again", produces={"plan": "plan v2"}))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "back", note="fix X")
    assert runner.drive(run_dir) == "waiting"
    assert len(calls("pick-up")) == 2 and calls("pick-up")[1]["answer"]["note"] == "fix X"
    assert calls("pick-up")[0]["answer"] is None
    gates.answer(open_gate(run_dir)["id"], "approve")
    assert runner.drive(run_dir) == "done"
    assert len(calls("pick-up")) == 2
    assert atomic.read_json(run_dir / "things.json")["plan"] == "plan v2"
    line = next(x for x in state.load(run_dir)["steps"] if x["step"] == "pick-up")
    assert line["status"] == "passed"


# 18
@pytest.mark.parametrize("action", ["skip", "stop"])
def test_step_gate_skip_and_stop(tmp_path, runner, action):
    on("acceptance", 1, None, gate(title="Is this right?"))
    run_dir = start(tmp_path, THREE)
    assert runner.drive(run_dir) == "waiting"
    assert open_gate(run_dir)["step"] == "acceptance"
    gates.answer(open_gate(run_dir)["id"], action)
    final = runner.drive(run_dir)
    st = state.load(run_dir)
    if action == "skip":
        assert final == "done"
        assert [st["tasks"][n]["status"] for n in "123"] == ["skipped", "skipped", "passed"]
        assert calls("commit", 1) == [] and len(calls("builder", 3)) == 1
    else:
        assert final == "stopped"
        assert calls("builder", 3) == [] and calls("summary") == [] and calls("notify")


def test_step_gate_skip_at_run_level_skips_only_the_step(tmp_path, runner):
    on("summary", None, None, gate(title="Summary looks odd"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "skip")
    assert runner.drive(run_dir) == "done"
    assert calls("notify")


def test_step_gate_unknown_action_recalls_step(tmp_path, runner):
    """An action the runner does not know (a new gate kind's own) re-calls the step with ctx.answer,
    like back but without adding to failures; ctx.answer.notes keeps every back note in order."""
    on("acceptance", 1, None, gate(title="Pick one", actions=["approve", "back", "tweak"]),
       gate(title="Pick one", actions=["approve", "back", "tweak"]),
       gate(title="Pick again", actions=["approve", "back", "tweak"]))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "back", note="fix X")
    assert runner.drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "tweak", note="bigger")
    assert runner.drive(run_dir) == "waiting"
    third = calls("acceptance")[2]["answer"]
    assert third["action"] == "tweak" and third["note"] == "bigger" and third["notes"] == ["fix X"]
    assert task(run_dir)["failures"] == ["Sent back by cli: fix X"]
    gates.answer(open_gate(run_dir)["id"], "approve")
    assert runner.drive(run_dir) == "done"


# 19
def test_restart_mid_gate_resumes_waiting(tmp_path, adapters, lib, project):
    on("builder", 1, 1, fail("broke"))
    run_dir = start(tmp_path, max_tries=1)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    # The runner process goes away; a new one starts from state.json.
    again = Runner(adapters, lib)
    assert again.drive(run_dir) == "waiting"
    assert watch.watch_once(adapters, again) is None
    assert len(list((run_dir / "gates").glob("*.json"))) == 1
    assert len(adapters.notify.messages) == 1
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert Runner(adapters, lib).drive(run_dir) == "done"


# 20
def test_answer_arrived_while_down(tmp_path, adapters, lib, project):
    on("acceptance", 1, 1, gate(title="Check the output", produces={"exit-codes": "seen by Alex"}))
    run_dir = start(tmp_path)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    gates.answer(open_gate(run_dir)["id"], "approve")        # written while no runner is alive
    assert watch.watch_once(adapters, Runner(adapters, lib)) == run_dir.name
    assert state.load(run_dir)["status"] == "done"
    assert len(calls("acceptance")) == 1 and len(calls("commit")) == 1
    assert calls("commit")[0]["things"]["exit-codes"] == "seen by Alex"


# 21
def test_usage_limit_is_not_a_try(tmp_path, runner, adapters):
    on("builder", 1, 1, UsageLimit(claude.Result(kind="rate_limited")), StepResult("pass"))
    run_dir = start(tmp_path)
    watch.watch_once(adapters, runner)
    assert state.load(run_dir)["status"] == "running"        # paused, then ready to go on
    watch.watch_once(adapters, runner)
    assert state.load(run_dir)["status"] == "done"
    assert attempts("builder") == [1, 1]
    assert task(run_dir)["tries"] == 1 and task(run_dir)["failures"] == []


# 22
def test_crashed_step_is_failed_attempt(tmp_path, runner):
    on("builder", 1, 1, RuntimeError("disk on fire\nsecond line"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    t = task(run_dir)
    assert t["failures"] == ["step builder crashed: RuntimeError: disk on fire"]
    assert t["tries"] == 2 and calls("builder")[1]["failures"] == t["failures"]


# 23
def test_run_stop_while_waiting(tmp_path, runner, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    on("builder", 1, 1, fail("broke"))
    run_dir = start(tmp_path, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    ops_runs.stop(run_dir.name)
    assert runner.drive(run_dir) == "stopped"
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert watch.watch_once(adapters, runner) is None
    assert runner.drive(run_dir) == "stopped"
    assert attempts("builder") == [1] and calls("summary") == []


# 24
def test_real_chat_adapter_command(tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        pid = 4242

        def __init__(self, argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs

        def poll(self):
            return None

    monkeypatch.setattr(chat.subprocess, "Popen", FakePopen)
    project_dir = tmp_path / "projects" / "proj"
    out = chat.delegate("proj", project_dir, "run.1", "fix task 1", tmp_path / "logs" / "delegate.log")
    assert out == {"started": True, "handle": "4242", "error": ""}
    argv, kw = seen["argv"], seen["kwargs"]
    assert argv[:3] == ["claude", "-p", "fix task 1"] and "--bare" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[argv.index("--output-format") + 1] == "text"
    assert kw["cwd"] == str(project_dir) and kw["start_new_session"] is True
    assert kw["env"]["PHOENIX_WHO"] == "chat:delegate"
    assert chat.status("4242") == "running"
    assert chat.status("999999999") == "exited"


def test_restart_after_failed_attempt_respects_max_tries(tmp_path, adapters, lib, project, monkeypatch):
    """A crash after attempt 1's result.json (failed) but before the failure mode ran: the restart
    must not start attempt 2 when max_tries is 1; it escalates."""
    on("builder", 1, None, fail("broke"))
    run_dir = start(tmp_path, max_tries=1)
    real = failmodes.after_last_try

    def crash(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(failmodes, "after_last_try", crash)
    with pytest.raises(RuntimeError):
        Runner(adapters, lib).drive(run_dir)
    assert failmodes.attempt_result(run_dir, 1, 1)["status"] == "failed"
    monkeypatch.setattr(failmodes, "after_last_try", real)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    assert attempts("builder") == [1]
    assert open_gate(run_dir)["kind"] == "escalation"
    gates.answer(open_gate(run_dir)["id"], "acknowledged")
    assert Runner(adapters, lib).drive(run_dir) == "waiting"        # exactly one more attempt, then ask again
    assert attempts("builder") == [1, 2]


@pytest.mark.parametrize("holder", ["step", "task"])
def test_gate_opened_but_not_held_is_adopted(tmp_path, runner, holder):
    """A crash between writing the gate file and recording it in state.json: the waiting run has no
    current.gate. The next drive adopts the newest unanswered gate and still wakes on its answer."""
    if holder == "step":
        on("acceptance", 1, None, gate(title="Check it"))
    else:
        on("builder", 1, None, fail("broke"))
    run_dir = start(tmp_path, max_tries=1)
    assert runner.drive(run_dir) == "waiting"
    g = open_gate(run_dir)

    def forget(s):                                  # what state.json looks like after that crash
        s["current"]["gate"] = None
        if holder == "step":
            line = next(x for x in s["steps"] if x["step"] == "acceptance")
            line.update(status="running", gate=None)
        else:
            s["tasks"]["1"]["gate"] = None
    state.update(run_dir, forget)
    assert watch.watch_once(runner.adapters, runner) is None            # the service loop adopts it
    assert state.load(run_dir)["current"]["gate"] == g["id"]
    assert runner.drive(run_dir) == "waiting"
    st = state.load(run_dir)
    assert st["current"]["gate"] == g["id"]
    assert len(gates.list_gates(open_only=False)) == 1                  # no second gate
    gates.answer(g["id"], "approve" if holder == "step" else "acknowledged")
    assert watch.watch_once(runner.adapters, runner) == run_dir.name
    if holder == "step":
        assert state.load(run_dir)["status"] == "done" and len(calls("acceptance")) == 1
    else:
        assert attempts("builder") == [1, 2]



def test_alex_answering_first_stops_the_delegate(tmp_path, runner, adapters):
    adapters.chat.mode = "run"
    on("builder", 1, 1, fail("flaky network"))
    run_dir = start(tmp_path, max_tries=1, on_failure="delegate")
    assert runner.drive(run_dir) == "waiting"
    gate_id = state.load(run_dir)["current"]["gate"]
    handle = state.load(run_dir)["tasks"]["1"]["delegate"]["handle"]
    assert adapters.chat.status(handle) == "running"
    gates.answer(gate_id, "skip", who="dashboard")
    runner.drive(run_dir)
    assert adapters.chat.status(handle) == "exited"
    assert adapters.chat.stopped == [handle]


def test_real_chat_reaps_finished_sessions(tmp_path):
    from phoenix9 import chat
    proc = __import__("subprocess").Popen(["true"])
    chat._started[str(proc.pid)] = proc
    proc.wait()
    chat._started[str(proc.pid)] = proc
    assert chat.status(str(proc.pid)) == "exited"
    assert str(proc.pid) not in chat._started
