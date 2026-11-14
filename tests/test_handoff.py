"""Hand to the agent: a task that runs out of tries is handed to the agent service once (ids only), or falls back to pause."""
import json
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import fail, on
from phoenix9 import failmodes, gates, paths, runs, state
from phoenix9.ops import gates as ops_gates
from phoenix9.runner import Runner

ONE = """# Spec: One task

## Task 1: Only thing
Goal: make it work.
Done when:
- it works
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path):
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return paths.projects() / "proj"


@pytest.fixture
def runner(adapters, tmp_path, project):
    scripted.reset()
    yield Runner(adapters, scripted.make_library(tmp_path / "lib"))
    scripted.reset()


@pytest.fixture
def sent(adapters):
    """Every hand-off the runner posts to the agent service (the fake agent takes each one)."""
    fake = adapters.agentnext
    fake.status, fake.chunks = 202, [b'{"thread_id": "t-1", "run_id": "r-1"}']
    return fake.calls


def start(tmp_path, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(ONE)
    return runs.create_run("proj", f, {"max_tries": 1, "on_failure": "delegate", **overrides})


def only_gate(run_dir) -> dict:
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    return g


HANDED = "the agent is looking at it"


def test_one_handoff_with_only_the_ids_and_one_notify_line(tmp_path, runner, adapters, sent):
    on("builder", 1, 1, fail("secret-looking failure text"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    assert g["kind"] == "escalation" and failmodes.HANDOFF_FLAG in g["flags"]
    (call,) = sent
    assert call["method"] == "POST" and call["url"] == "http://agent.invalid/handoffs"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["timeout"] == failmodes.HANDOFF_TIMEOUT
    assert json.loads(call["body"]) == {"run_id": run_dir.name, "task": 1, "gate_id": g["id"], "project": "proj"}
    assert b"secret-looking" not in call["body"]
    assert adapters.notify.messages == [
        "Phoenix: task 1 of proj ran out of tries; the agent is looking at it. Open the agent to see what it suggests."]
    assert runner.drive(run_dir) == "waiting" and len(sent) == 1 and len(adapters.notify.messages) == 1


def test_a_repeat_answer_with_a_thread_counts_as_handed_over(tmp_path, runner, adapters, sent):
    adapters.agentnext.status, adapters.agentnext.chunks = 200, [b'{"thread_id": "t-1", "run_id": null}']
    on("builder", 1, 1, fail("x"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    assert failmodes.HANDOFF_FLAG in only_gate(run_dir)["flags"]


def test_agent_answer_runs_one_more_attempt(tmp_path, runner, sent):
    on("builder", 1, 1, fail("flaky"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    assert runner.drive(run_dir) == "done"


def assert_paused(run_dir, adapters, words):
    g = only_gate(run_dir)
    assert failmodes.HANDOFF_FLAG not in g["flags"]
    assert g["flags"] == [f"could not be handed to the Phoenix agent ({words}); waiting for you"]
    (told,) = adapters.notify.messages
    assert "needs you" in told and words in told and HANDED not in told


def test_unreachable_agent_falls_back_to_pause(tmp_path, runner, adapters):
    adapters.agentnext.down = True
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert_paused(run_dir, adapters, "it isn't answering")
    assert runner.drive(run_dir) == "waiting" and len(adapters.notify.messages) == 1


def test_no_token_file_falls_back_to_pause(tmp_path, runner, adapters):
    Path(adapters.agentnext.token_file).unlink()
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert_paused(run_dir, adapters, "it isn't set up yet")
    assert adapters.agentnext.calls == []


def test_agent_not_set_up_falls_back_to_pause(tmp_path, runner, adapters):
    adapters.agentnext.set_up = False
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert_paused(run_dir, adapters, "it isn't set up yet")
    assert adapters.agentnext.calls == []


def test_no_key_409_falls_back_to_pause_with_its_plain_words(tmp_path, runner, adapters):
    adapters.agentnext.status = 409
    adapters.agentnext.chunks = [b'{"error": "The agent has no API key yet, so it cannot look at this build. '
                                 b'Phoenix keeps the question for Alex."}']
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert_paused(run_dir, adapters, "The agent has no API key yet, so it cannot look at this build")


@pytest.mark.parametrize("status,chunks", [(500, [b"oops"]), (400, [b'{"error": "bad"}']),
                                           (202, [b'{"run_id": "r"}']), (200, [b"not json"])])
def test_odd_answers_fall_back_to_pause(tmp_path, runner, adapters, status, chunks):
    adapters.agentnext.status, adapters.agentnext.chunks = status, chunks
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    assert_paused(run_dir, adapters, failmodes.ODD_ANSWER)


def test_at_most_two_hand_offs_then_pause(tmp_path, runner, adapters, sent):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    for _ in range(failmodes.MAX_ESCALATIONS):
        assert runner.drive(run_dir) == "waiting"
        gates.answer(only_gate(run_dir)["id"], "acknowledged", who="agent")
    runner.drive(run_dir)
    assert len(sent) == failmodes.MAX_ESCALATIONS
    assert state.load(run_dir)["tasks"]["1"]["status"] == "failed"


def test_agent_may_only_acknowledge_a_handed_over_gate():
    flagged = {"kind": "escalation", "flags": [failmodes.HANDOFF_FLAG]}
    assert gates.may_answer(flagged, "agent", {}, "acknowledged")
    assert not gates.may_answer(flagged, "agent", {}, "skip")
    assert not gates.may_answer(flagged, "agent", {}, "stop")


def test_ops_refuses_agent_skip_on_a_handed_over_gate(tmp_path, runner, sent):
    on("builder", 1, 1, fail("x"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gid = only_gate(run_dir)["id"]
    with pytest.raises(Exception, match="may not answer"):
        ops_gates.answer(gid, "skip", who="agent")
    ops_gates.answer(gid, "acknowledged", who="agent")


def test_home_chat_may_only_acknowledge_a_handed_over_gate():
    flagged = {"kind": "escalation", "flags": [failmodes.HANDOFF_FLAG]}
    plain = {"kind": "escalation", "flags": []}
    assert gates.may_answer(flagged, "chat:home", {}, "acknowledged")
    assert not gates.may_answer(flagged, "chat:home", {}, "skip")
    assert not gates.may_answer(flagged, "chat:home", {}, "stop")
    assert not gates.may_answer(plain, "chat:home", {}, "acknowledged")
    assert not gates.may_answer(flagged, "chat:delegate", {}, "acknowledged")
    assert gates.may_answer(plain, "dashboard", {}, "skip")


def test_ops_refuses_home_chat_skip(tmp_path, runner, sent):
    on("builder", 1, 1, fail("x"))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gid = only_gate(run_dir)["id"]
    with pytest.raises(Exception, match="may not answer"):
        ops_gates.answer(gid, "skip", who="chat:home")
    ops_gates.answer(gid, "acknowledged", who="chat:home")


def test_old_state_with_delegate_field_still_loads(tmp_path, runner, sent):
    run_dir = start(tmp_path)
    state.update(run_dir, lambda s: s["tasks"]["1"].__setitem__("delegate", {"handle": "99", "gate": "x"}))
    assert runner.drive(run_dir) == "done"


def test_chat_module_has_no_headless_session():
    from phoenix9 import chat
    assert not any(hasattr(chat, n) for n in ("delegate", "reap", "stop", "status")) and chat.agent_restart
