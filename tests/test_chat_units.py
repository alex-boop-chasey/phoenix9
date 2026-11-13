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
    assert h.calls[-3:] == [["systemctl", "is-enabled", U], ["systemctl", "start", U],
                            ["systemctl", "disable", "--now", U]]


def test_start_unit_never_enables_and_removes_a_leftover_enable(projects):
    """Waking a chat must not make a server reboot wake it too; an old enable is taken away."""
    h = FakeHost()
    h.script(["systemctl", "is-enabled", U], out="enabled\n")
    chat.start_unit(h, "alpha")
    assert h.calls == [["systemctl", "is-enabled", U], ["systemctl", "disable", U], ["systemctl", "start", U]]


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


LIST = ("claude-rc-chat@alpha.service loaded active running Claude chat for alpha\n"
        "claude-rc-chat@gone.service  loaded active running Claude chat for gone\n"
        "claude-rc-chat@old.v2.service loaded active running Claude chat for old.v2\n")


def test_stray_units_are_active_chats_of_names_that_are_not_listed(projects):
    """Listed projects are never strays; one systemctl list call through the Host adapter finds the rest."""
    h = FakeHost()
    h.script(["systemctl", "list-units"], out=LIST)
    assert chat.stray_units(h) == ["gone", "old.v2"]
    assert h.calls == [["systemctl", "list-units", "claude-rc-chat@*", "--state=active", "--plain", "--no-legend"]]
    h.script(["systemctl", "list-units"], rc=1, err="Access denied")
    assert chat.stray_units(h) == []


def test_stop_stray_stops_and_disables_only_unlisted_good_names(projects):
    """A stray is stopped and disabled; listed and bad names are refused before any systemctl call."""
    h = FakeHost()
    chat.stop_stray(h, "gone")
    assert h.calls == [["systemctl", "stop", "claude-rc-chat@gone"], ["systemctl", "disable", "claude-rc-chat@gone"]]
    h.calls.clear()
    for listed in ("alpha", "beta"):
        with pytest.raises(ValueError, match="is a listed project"):
            chat.stop_stray(h, listed)
    for bad in ("", "../alpha", "alpha;ls", "-x", ".hidden", "a b", "x/y", None):
        with pytest.raises(ValueError, match="not a valid chat name"):
            chat.stop_stray(h, bad)
    assert h.calls == []
    h.script(["systemctl", "stop"], rc=1, err="Access denied")
    with pytest.raises(RuntimeError, match="Access denied"):
        chat.stop_stray(h, "gone")


def test_chat_tidy_cli_lists_then_stops_with_yes(projects, monkeypatch, capsys):
    """`phoenix chat tidy` only lists; with --yes it stops each stray and records one command event each."""
    from phoenix9 import paths
    from phoenix9.__main__ import main
    from phoenix9.ops import common
    from tests.fakes import fake_adapters
    fakes = fake_adapters(projects.parent)
    fakes.host.script(["systemctl", "list-units"], out=LIST)
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    assert main(["chat", "tidy"]) == 0
    out = capsys.readouterr().out
    assert "gone" in out and "old.v2" in out and "alpha" not in out and "phoenix chat tidy --yes" in out
    assert not [c for c in fakes.host.calls if c[1:2] in (["stop"], ["disable"])]
    assert main(["chat", "tidy", "--yes"]) == 0
    assert "Stopped the chat for gone." in capsys.readouterr().out
    assert [c for c in fakes.host.calls if c[1:2] == ["stop"]] == [
        ["systemctl", "stop", "claude-rc-chat@gone"], ["systemctl", "stop", "claude-rc-chat@old.v2"]]
    logged = (paths.logs() / "commands.jsonl").read_text()
    assert logged.count("chat tidy gone") == 1 and logged.count("chat tidy old.v2") == 1
