"""Hand to the Phoenix agent: a task that runs out of tries is handed over with ONE message, or falls back to pause."""
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import fail, on
from phoenix9 import chatlink, failmodes, gates, paths, runs, state
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
def sent(monkeypatch):
    """Every message the runner posts to the agent (the real send is never called)."""
    box = []

    def fake_send(text, context=None, who="cli", **kw):
        box.append({"text": text, "context": context, "who": who})
        return {"sent": True}
    monkeypatch.setattr(chatlink, "send", fake_send)
    return box


def start(tmp_path, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(ONE)
    return runs.create_run("proj", f, {"max_tries": 1, "on_failure": "delegate", **overrides})


def only_gate(run_dir) -> dict:
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    return g


def test_one_message_and_flag_and_no_notify(tmp_path, runner, adapters, sent):
    on("builder", 1, 1, fail("secret-looking failure text"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    assert g["kind"] == "escalation" and failmodes.HANDOFF_FLAG in g["flags"]
    assert [m["text"] for m in sent] == [f"[Phoenix · escalation] {run_dir.name} task 1"]
    assert sent[0]["who"] == failmodes.HANDOFF_WHO == "build escalation"
    assert chatlink.from_name(sent[0]["who"]) == "Phoenix (build escalation)"
    assert adapters.notify.messages == []
    assert runner.drive(run_dir) == "waiting" and len(sent) == 1


def test_agent_answer_runs_one_more_attempt(tmp_path, runner, sent):
    on("builder", 1, 1, fail("flaky"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gates.answer(only_gate(run_dir)["id"], "acknowledged", who="chat:home")
    assert runner.drive(run_dir) == "done"


def test_asleep_agent_falls_back_to_pause(tmp_path, runner, adapters, monkeypatch):
    def asleep(*a, **k):
        raise chatlink.SendError("The Phoenix agent is asleep (no running session found). Nothing was sent.")
    monkeypatch.setattr(chatlink, "send", asleep)
    on("builder", 1, 1, fail("broken"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    g = only_gate(run_dir)
    assert failmodes.HANDOFF_FLAG not in g["flags"] and any("asleep" in f for f in g["flags"])
    assert len(adapters.notify.messages) == 1 and "needs you" in adapters.notify.messages[0]
    assert runner.drive(run_dir) == "waiting" and len(adapters.notify.messages) == 1


def test_at_most_two_hand_offs_then_pause(tmp_path, runner, adapters, sent):
    on("builder", 1, None, fail("still broken"))
    run_dir = start(tmp_path)
    for _ in range(failmodes.MAX_ESCALATIONS):
        assert runner.drive(run_dir) == "waiting"
        gates.answer(only_gate(run_dir)["id"], "acknowledged", who="chat:home")
    runner.drive(run_dir)
    assert len(sent) == failmodes.MAX_ESCALATIONS
    assert state.load(run_dir)["tasks"]["1"]["status"] == "failed"


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
