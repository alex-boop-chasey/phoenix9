"""Phoenix never reads Claude's login (.credentials.json) or the per-session peer keys (sessions/*.key)."""
import builtins
import io
import json
import os
from pathlib import Path

import pytest

from phoenix9 import chatlink
from phoenix9.adapters import Host

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ".credentials" + ".json"     # split so this file does not name it in one piece


def test_no_module_names_the_credentials_file():
    hits = []
    for folder in ("phoenix9", "steps", "bin"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if FORBIDDEN in text:
                    hits.append(str(path.relative_to(ROOT)))
    assert hits == []


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    """A Claude home with a live agent session, its .key file and a credentials file."""
    home = tmp_path / "claude"
    (home / "sessions").mkdir(parents=True)
    folder = tmp_path / "agent"
    folder.mkdir()
    (home / FORBIDDEN).write_text('{"token": "x"}')
    sid = "aaaaaaaa-1111-4111-8111-111111111111"
    sock = "/tmp/cc-socks-0/%d.sock" % os.getpid()
    (home / "sessions" / ("%d.json" % os.getpid())).write_text(json.dumps({
        "pid": os.getpid(), "cwd": str(folder), "name": "Phoenix agent", "status": "idle",
        "messagingSocketPath": sock, "sessionId": sid}))
    (home / "sessions" / ("%d.abc.key" % os.getpid())).write_text('{"peerToken": "x"}')
    tdir = Path(chatlink.transcript_dir(str(home), str(folder)))
    tdir.mkdir(parents=True)
    (tdir / (sid + ".jsonl")).write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    monkeypatch.setattr(chatlink.settings, "agent_settings",
                        lambda: {"folder": str(folder), "unit": "x"})
    monkeypatch.setattr(Host, "exists", lambda self, p: True if p == sock else os.path.exists(p))
    monkeypatch.setattr(Host, "systemctl", lambda self, *a: (0, "0\n", ""))
    return home


def test_chatlink_never_opens_key_or_credentials_files(claude_home, monkeypatch):
    opened = []
    real_open, real_io_open, real_read_text = builtins.open, io.open, Path.read_text

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    def spy_read_text(self, *a, **k):
        opened.append(str(self))
        return real_read_text(self, *a, **k)
    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    monkeypatch.setattr(Path, "read_text", spy_read_text)
    found = chatlink.find(str(claude_home))
    assert found is not None and found["transcript"]
    assert opened, "the spy saw no reads at all"
    bad = [p for p in opened if p.endswith(".key") or p.endswith(FORBIDDEN)]
    assert bad == []
