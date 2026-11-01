"""Tests for the adapters and their fakes."""
import pytest

from phoenix9 import adapters as ad


def test_notify_truncates_and_writes(tmp_path):
    """Notify writes the file named by PHOENIX_NOTIFY_FILE, cut to 600 characters."""
    ad.Notify().send("x" * 700)
    assert (tmp_path / "notify.msg").read_text() == "x" * 600


def test_fake_host_records_and_replays(adapters):
    """Scripted answers are chosen by argv prefix and calls are recorded."""
    h = adapters.host
    h.script(["systemctl", "status"], rc=3, out="inactive")
    assert h.systemctl("status", "x") == (3, "inactive", "")
    assert h.run(["ls"]) == (0, "", "")
    assert h.calls == [["systemctl", "status", "x"], ["ls"]]


def test_fake_clock_sleep_advances(adapters):
    """Sleeping moves the manual clock."""
    c = adapters.clock
    t = c.now()
    c.sleep(5)
    assert c.now() == t + 5


def test_fake_http_and_notify(adapters):
    """Http answers by (method, url); notify collects messages."""
    adapters.http.script("get", "http://x/y", 200, body=b"ok")
    assert adapters.http.request("GET", "http://x/y")[2] == b"ok"
    assert adapters.http.request("GET", "http://x/z")[0] == 404
    adapters.notify.send("hi")
    assert adapters.notify.messages == ["hi"]


def test_real_builds_without_touching_system():
    """real() only builds objects; unwritten methods raise NotImplementedError."""
    a = ad.real()
    assert isinstance(a.host, ad.Host) and isinstance(a.clock, ad.Clock)
    with pytest.raises(NotImplementedError):
        a.docker.run_step()
    with pytest.raises(NotImplementedError):
        a.chat.delegate()
