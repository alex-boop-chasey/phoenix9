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
        a.claude.run_session()
    assert isinstance(a.chat, ad.Chat) and callable(a.chat.status)


def test_host_reads(tmp_path):
    """The real Host lists, stats and reads files, and says nothing is there when missing."""
    import os
    tmp_path = tmp_path / "own"
    tmp_path.mkdir()
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    h = ad.Host()
    assert h.list_dir(tmp_path) == ["a.txt"] and h.list_dir(tmp_path / "no") == []
    assert h.exists(tmp_path / "a.txt") and not h.exists(tmp_path / "no")
    assert h.pid_alive(os.getpid()) and not h.pid_alive(99999999)
    assert h.stat(tmp_path / "a.txt")["uid"] == os.getuid() and h.stat(tmp_path / "no") is None
    assert h.read_lines(tmp_path / "a.txt") == ["one\n", "two\n"] and h.read_lines(tmp_path / "no") == []


def test_fake_host_reads(adapters):
    """FakeHost serves the same calls from .files, .dirs, .pids and .stats."""
    h = adapters.host
    h.files["/x/a.txt"] = "l1\nl2\n"
    h.dirs["/d"] = ["p"]
    h.pids.add(7)
    h.stats["/x/a.txt"] = {"mode": 0o600, "uid": 0}
    assert h.read_lines("/x/a.txt") == ["l1\n", "l2\n"] and h.read_lines("/x/no") == []
    assert h.list_dir("/d") == ["p"] and h.list_dir("/x") == ["a.txt"] and h.list_dir("/no") == []
    assert h.exists("/d") and h.exists("/x/a.txt") and not h.exists("/no")
    assert h.pid_alive(7) and not h.pid_alive(8)
    assert h.stat("/x/a.txt") == {"mode": 0o600, "uid": 0} and h.stat("/no") is None


def test_host_parent_pid_and_realpath(tmp_path):
    import os
    from phoenix9.adapters import Host
    assert Host().parent_pid(os.getpid()) == os.getppid()
    assert Host().parent_pid(2 ** 22 + 12345) is None
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert Host().realpath(str(tmp_path / "link")) == str((tmp_path / "real").resolve())
