"""Tests for the project chat unit helpers (FakeHost only)."""
import json

import pytest

from phoenix9 import chatlink, chat
from tests.fakes import FakeHost

U = "claude-rc-chat@alpha"


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """Two listed projects and one plain folder, in a temp projects folder."""
    root = tmp_path / "projects"
    for n in ("alpha", "beta"):
        (root / n).mkdir(parents=True)
        (root / n / "CLAUDE.md").write_text("x")
    (root / "nofile").mkdir()
    monkeypatch.setenv("PHOENIX_PROJECTS", str(root))
    monkeypatch.setenv("PHOENIX_HOME", str(tmp_path / "home"))
    chatlink.forget()
    return root


def test_chat_unit_names(projects):
    """Only listed project names make a unit name."""
    assert chat.chat_unit("alpha") == U
    for bad in ("nofile", "ghost", "", "../alpha", "alpha;ls"):
        with pytest.raises(ValueError):
            chat.chat_unit(bad)


def test_state_pid_start_stop(projects):
    """The helpers call systemctl with the right words."""
    h = FakeHost()
    h.script(["systemctl", "is-active", U], rc=3, out="failed\n")
    assert chat.unit_state(h, "alpha") == "failed"
    h.script(["systemctl", "show"], out="42\n")
    assert chat.unit_main_pid(h, "alpha") == 42
    chat.start_unit(h, "alpha")
    chat.stop_unit(h, "alpha")
    assert h.calls[-2] == ["systemctl", "enable", "--now", U]
    assert h.calls[-1] == ["systemctl", "disable", "--now", U]


def test_stop_conversation_rules(projects):
    """Only the unit's direct child or a registry entry of the project is stopped."""
    h = FakeHost()
    h.pids |= {100, 200, 201, 300}
    h.parents.update({200: 100, 201: 200, 300: 1})
    h.script(["systemctl", "show"], out="100\n")
    chat.stop_conversation(h, "alpha", 200)
    for pid in (201, 300):
        with pytest.raises(ValueError):
            chat.stop_conversation(h, "alpha", pid)
    assert h.stopped == [200]


def test_stop_conversation_registry(projects):
    """A live registry entry for the project may be stopped; another project's may not."""
    h = FakeHost()
    h.script(["systemctl", "show"], out="0\n")
    for pid, name in ((500, "alpha"), (501, "beta")):
        sock = f"/tmp/cc-socks-0/s{pid}.sock"
        h.files[f"/root/.claude/sessions/{pid}.json"] = json.dumps(
            {"pid": pid, "cwd": str(projects / name), "name": "x", "messagingSocketPath": sock})
        h.files[sock] = ""
        h.pids.add(pid)
    chat.stop_conversation(h, "alpha", 500)
    with pytest.raises(ValueError):
        chat.stop_conversation(h, "alpha", 501)
    assert h.stopped == [500]


def test_start_unit_reports_a_refusing_systemd_plainly(projects):
    """When systemd refuses (e.g. the unit template is missing) the user sees why at once, not a 60 s wait."""
    import pytest
    from phoenix9 import chat as chat_mod
    from phoenix9.projectchat import NotReady

    class Host:
        def systemctl(self, *args):
            return 1, "", "Failed to enable unit: Unit file claude-rc-chat@test.service does not exist.\n"

    with pytest.raises(NotReady) as e:
        chat_mod.start_unit(Host(), "alpha")
    assert "couldn't start the chat service claude-rc-chat@alpha" in str(e.value)
    assert "does not exist" in str(e.value)


def test_chat_unit_template_has_the_settings_a_live_chat_needs():
    """Found live: with `env claude` and no PATH the unit failed (status 127) and restarted forever."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "deploy" / "claude-rc-chat@.service").read_text()
    assert "ExecStart=/opt/phoenix9/deploy/chat-launch.sh %i" in text and "/usr/bin/env claude" not in text
    assert "Environment=PATH=/root/.local/bin:" in text
    assert "Environment=IS_SANDBOX=1" in text and "Environment=HOME=/root" in text
    assert "Environment=PHOENIX_WHO=chat:%i" in text and "MemoryMax=" in text
    assert "StartLimitBurst=" in text and "[Install]" in text
    assert "KillMode=mixed" in text and "TimeoutStopSec=30" in text
    assert "WorkingDirectory=/srv/projects/%i" in text
    launcher = (Path(__file__).resolve().parent.parent / "deploy" / "chat-launch.sh").read_text()
    assert "/root/.local/bin/claude" in launcher and "--create-session-in-dir" in launcher
