"""Tests for planning sessions: start, continue, status, list, one running per project (fake host, no real Claude)."""
import json
import types

import pytest

from phoenix9 import chat, events, paths, plans
from phoenix9.__main__ import main
from tests.fakes import FakeHost

SPEC = "## Open questions\n1. Which db? Recommended: sqlite\nAnswer:\n2. Name? Recommended: x\nAnswer: yes\n"


@pytest.fixture
def proj(phoenix_env):
    """A project folder with a notes/specs/ folder."""
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes" / "specs").mkdir(parents=True)
    return folder


def _stream(text, sid="sess-1"):
    return "\n".join(json.dumps(o) for o in (
        {"type": "system", "session_id": sid}, {"type": "result", "result": text, "session_id": sid})) + "\n"


def _ad(host):
    return types.SimpleNamespace(host=host)


def test_start_runs_claude_in_project_folder(proj):
    (proj / "notes/specs/s.md").write_text(SPEC)
    host = FakeHost()
    host.script(["claude"], out=_stream("PLAN REPORT: notes/specs/s.md, 1 open questions"))
    rec = chat.plan_start("demo", "plan a thing", None, adapters=_ad(host))
    argv = host.calls[0]
    assert argv[:2] == ["claude", "-p"] and argv[argv.index("--model") + 1] == "claude-fable-5-1"
    assert "stream-json" in argv and "--resume" not in argv and "--bare" not in argv
    assert host.cwds[0] == str(proj)
    assert "Open questions" in argv[-1] and "phoenix spec check" in argv[-1]
    assert rec["status"] == "waiting" and rec["open_questions"] == 1 and rec["session_id"] == "sess-1"
    assert plans.session_file(rec["id"]).exists()
    assert any(e["type"] == "plan.waiting" for e in events.read(paths.events()))


def test_continue_resumes_and_finishes(proj):
    (proj / "notes/specs/s.md").write_text(SPEC)
    host = FakeHost()
    host.script(["claude"], out=_stream("PLAN REPORT: notes/specs/s.md, 1 open questions"))
    rec = chat.plan_start("demo", "x", "m1", adapters=_ad(host))
    (proj / "notes/specs/s.md").write_text("## Decisions\n1. sqlite\n")
    host.script(["claude"], out=_stream("PLAN REPORT: notes/specs/s.md, 0 open questions"))
    rec = chat.plan_continue(rec["id"], adapters=_ad(host))
    argv = host.calls[1]
    assert argv[argv.index("--resume") + 1] == "sess-1" and "Decisions" in argv[-1]
    assert rec["status"] == "done" and rec["open_questions"] == 0


def test_failed_and_one_running(proj):
    host = FakeHost()
    host.script(["claude"], rc=1, err="boom")
    assert chat.plan_start("demo", "x", None, adapters=_ad(host))["status"] == "failed"
    running = plans.new_record("demo", "other", "m", "cli")
    with pytest.raises(plans.PlanError, match="already has"):
        plans.new_record("demo", "again", "m", "cli")
    assert running["status"] == "running"


def test_model_setting(proj, phoenix_env):
    assert plans.plan_model() == "claude-fable-5-1"


def test_count_open():
    assert plans.count_open(SPEC) == 1


def test_cli_status_list_and_spec_check(proj, capsys, tmp_path):
    rec = plans.new_record("demo", "hello", "m", "cli")
    assert main(["plan", "status", rec["id"]]) == 0
    assert "running" in capsys.readouterr().out
    assert main(["plan", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["id"] == rec["id"]
    assert main(["plan", "status", "nope"]) != 0
    bad = tmp_path / "bad.md"
    bad.write_text("nothing\n")
    assert main(["spec", "check", str(bad)]) == 1
