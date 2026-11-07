"""Tests for the `phoenix agent` commands: brief, status, send and read, on a fake host."""
import json
import types

import pytest

from phoenix9 import agentlink, events, paths
from phoenix9.__main__ import main
from phoenix9.ops import agent, common, projects

CH = "/root/.claude"
TDIR = CH + "/projects/-srv-projects-home"
S1 = "aaaaaaaa-1111-4111-8111-111111111111"
S0 = "bbbbbbbb-0000-4000-8000-000000000000"


def run(capsys, *argv):
    """Run one command and return (code, stdout, stderr)."""
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def fake_rows(n, **extra):
    """n fake project rows."""
    return [{"name": "project-%02d" % i, "repo": "alex/project-%02d" % i, "profile": "quick",
             "needs_you": 0, "run": None, **extra} for i in range(n)]


@pytest.fixture
def host(monkeypatch):
    """A fake host with a live agent session."""
    from tests.fakes import FakeHost
    h = FakeHost()
    monkeypatch.setattr(common, "make_adapters", lambda: types.SimpleNamespace(host=h))
    monkeypatch.setattr(agent.update, "status", lambda *a, **k: {"update_available": False})
    h.files[CH + "/sessions/100.json"] = json.dumps({
        "pid": 100, "cwd": "/srv/projects/home", "name": "Phoenix agent", "status": "idle",
        "messagingSocketPath": "/tmp/cc-socks-0/x.sock", "kind": "interactive", "sessionId": S1})
    h.files["/tmp/cc-socks-0/x.sock"] = ""
    h.pids.add(100)
    h.files[TDIR + "/" + S1 + ".jsonl"] = "\n".join(json.dumps(o) for o in [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello there"}]}}]) + "\n"
    return h


def test_brief_lines(host, monkeypatch, capsys):
    """One line per project in the agreed words, plus NOW.md and the version."""
    rows = fake_rows(4)
    rows[1].update(needs_you=2)
    rows[2].update(run={"status": "running", "task": 3, "tasks": 7})
    rows[3].update(run={"status": "paused-limit", "task": 3, "tasks": 7}, repo=None)
    monkeypatch.setattr(projects, "rows", lambda only=None: rows)
    host.files["/srv/projects/home/notes/NOW.md"] = "\n".join("note %d" % i for i in range(30))
    code, out, _ = run(capsys, "agent", "brief")
    assert code == 0
    assert "project-00 · idle · alex/project-00" in out
    assert "project-01 · waiting for you (2) · " in out
    assert "project-02 · build running (task 3/7, Quick) · " in out
    assert "project-03 · paused · no repo" in out
    assert "note 19" in out and "note 20" not in out
    assert "Phoenix 9." in out and "update available" not in out


def test_brief_update_available(host, monkeypatch):
    """The brief says when an update is available."""
    monkeypatch.setattr(projects, "rows", lambda only=None: [])
    monkeypatch.setattr(agent.update, "status", lambda *a, **k: {"update_available": True})
    assert "update available" in agent.brief()["version"]


def test_brief_small_for_30_projects(host, monkeypatch, capsys):
    """30 projects stay under 2,000 tokens (4 characters a token)."""
    rows = fake_rows(30, repo="alex/" + "x" * 200)
    monkeypatch.setattr(projects, "rows", lambda only=None: rows)
    host.files["/srv/projects/home/notes/NOW.md"] = "\n".join("n" * 100 for _ in range(40))
    data = agent.brief()
    assert all(len(line) <= 120 for line in data["projects"]) and len(data["projects"]) == 30
    assert len(data["text"]) / 4 < 2000
    code, out, _ = run(capsys, "agent", "brief", "--json")
    assert json.loads(out)["projects"] == data["projects"]


def test_status(host, capsys):
    """Status in words and JSON, and asleep once the session is gone."""
    code, out, _ = run(capsys, "agent", "status")
    assert code == 0 and "idle" in out
    assert json.loads(run(capsys, "agent", "status", "--json")[1])["state"] == "idle"
    host.pids.clear()
    assert "asleep" in run(capsys, "agent", "status")[1]


def test_send_passes_context_and_records_event(host, monkeypatch, capsys):
    """Send hands the text and context to the link and records a command event."""
    seen = {}

    def fake_send(text, context=None, who="cli", **kw):
        seen.update(text=text, context=context, who=who)
        return {"sent": True, "at": "now", "after_line": 2}
    monkeypatch.setattr(agentlink, "send", fake_send)
    code, out, _ = run(capsys, "agent", "send", "hello", "--page", "projects", "--project", "p1", "--run", "r1")
    assert code == 0 and "Sent" in out
    assert seen == {"text": "hello", "context": {"page": "projects", "project": "p1", "run": "r1"}, "who": "cli"}
    code, out, _ = run(capsys, "agent", "send", "x", "--json")
    assert json.loads(out)["sent"] is True


def test_send_when_asleep(host, capsys):
    """Sending to a sleeping agent is refused in plain words."""
    host.pids.clear()
    code, _, err = run(capsys, "agent", "send", "hi")
    assert code == 1 and "asleep" in err


def test_read_items(host, capsys):
    """Read prints plain lines, honours --after and --tail, and has JSON."""
    code, out, _ = run(capsys, "agent", "read")
    assert code == 0 and "hi" in out and "hello there" in out
    assert "hi" not in run(capsys, "agent", "read", "--after", "1")[1]
    tail = run(capsys, "agent", "read", "--tail", "1")[1]
    assert "hello there" in tail and "hi" not in tail
    assert len(json.loads(run(capsys, "agent", "read", "--json")[1])["items"]) == 2


def test_help_lists_agent(capsys):
    """phoenix --help lists the agent group."""
    code, out, _ = run(capsys, "--help")
    assert "agent" in out


def test_brief_budget_with_long_lines(host, monkeypatch):
    """NOW.md lines are cut to 120 characters and the whole brief stays within 7,900 characters."""
    rows = fake_rows(150, repo="alex/" + "x" * 300)
    monkeypatch.setattr(projects, "rows", lambda only=None: rows)
    host.files["/srv/projects/home/notes/NOW.md"] = "\n".join("note-%d " % i + "n" * 5000 for i in range(20))
    data = agent.brief()
    assert all(len(line) <= 120 for line in data["now"]) and data["now"]
    assert len(data["text"]) <= 7900
    assert data["text"].endswith(data["version"])
    assert "more projects" in data["text"] and "note-19 " in data["text"]
    assert data["text"].splitlines()[0].startswith("project-00 · ")


def test_brief_fits_without_cutting_when_small(host, monkeypatch):
    rows = fake_rows(3)
    monkeypatch.setattr(projects, "rows", lambda only=None: rows)
    host.files["/srv/projects/home/notes/NOW.md"] = "short note"
    data = agent.brief()
    assert "more projects" not in data["text"] and "short note" in data["text"]


def test_agent_restart_needs_yes_and_restarts_the_unit(host, monkeypatch, capsys):
    """`phoenix agent restart --yes` restarts the agent's unit (the doctor's fix text names this command)."""
    from tests.fakes import FakeNotify
    notify = FakeNotify()
    monkeypatch.setattr(common, "make_adapters", lambda: types.SimpleNamespace(host=host, notify=notify))
    code, out, err = run(capsys, "agent", "restart")
    assert code == 1 and "--yes" in out + err
    assert not [c for c in host.calls if c[:2] == ["systemctl", "restart"]]
    code, out, _ = run(capsys, "agent", "restart", "--yes")
    assert code == 0 and "restart" in out.lower()
    assert ["systemctl", "restart", "claude-rc@home"] in host.calls
    assert notify.messages and "asked by cli" in notify.messages[0]


def test_doctor_fix_text_names_only_real_agent_commands():
    import re
    from phoenix9 import doctor
    from phoenix9.__main__ import build_parser
    source = open(doctor.__file__, encoding="utf-8").read()
    for cmd in set(re.findall(r"`phoenix agent (\w+)", source)):
        with pytest.raises(SystemExit) as stop:
            build_parser().parse_args(["agent", cmd, "--help"])
        assert stop.value.code == 0, cmd


def test_rules_file_mentions_project_chats():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "deploy/agent/agent-rules.md").read_text()
    assert "phoenix chat open" in text and "phoenix chat sleep" in text
    assert "Ask Alex first before `phoenix chat off" in text
    assert ".phoenix/chat.md" in text
