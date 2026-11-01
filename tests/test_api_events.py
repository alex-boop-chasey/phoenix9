"""Tests for the live events stream and the polling fallback."""
import http.client
import json
import socket
import threading
import time

import pytest

from phoenix9 import paths
from phoenix9.api import server, stream


@pytest.fixture
def live(monkeypatch):
    """A running API server with fast tail/ping intervals; returns (httpd, port)."""
    monkeypatch.setenv("PHOENIX_API_TAIL_SECONDS", "0.05")
    monkeypatch.setenv("PHOENIX_API_PING_SECONDS", "0.3")
    httpd = server.make_server(0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield httpd, httpd.server_address[1]
    httpd.stopping.set()
    httpd.shutdown()
    httpd.server_close()


def add(*events):
    """Append event lines (dicts or raw strings) to HOME/events.jsonl."""
    path = paths.events()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for e in events:
            f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")


def ev(project="p", type="run.started"):
    return {"ts": "2026-01-01T00:00:00+00:00", "type": type, "project": project, "run": "r", "task": None,
            "step": None, "data": {}}


def open_stream(port, path="/api/events", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers=headers or {})
    return conn, conn.getresponse()


def read_until(resp, text, limit=5.0):
    """Read from the stream until `text` shows up (or the time runs out); returns what was read."""
    got = b""
    end = time.time() + limit
    while text.encode() not in got and time.time() < end:
        try:
            chunk = resp.fp.readline()
        except (socket.timeout, TimeoutError):
            continue
        if not chunk:
            break
        got += chunk
    return got.decode()


def test_sse_streams_new_lines_with_line_ids(live):
    add(ev(), ev())
    conn, resp = open_stream(live[1])
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    assert resp.getheader("Cache-Control") == "no-store"
    assert resp.getheader("X-Accel-Buffering") == "no"
    assert resp.getheader("Content-Length") is None
    read_until(resp, ": connected")
    add("not json", ev(type="run.finished"))
    got = read_until(resp, "run.finished")
    assert "id: 4\nevent: run.finished" in got
    assert "id: 3" not in got
    conn.close()


def test_sse_resumes_from_last_event_id(live):
    add(ev(type="run.started"), ev(type="run.finished"), ev(type="gate.opened"))
    conn, resp = open_stream(live[1], headers={"Last-Event-ID": "1"})
    got = read_until(resp, "gate.opened")
    assert "id: 2" in got and "id: 3" in got and "id: 1\n" not in got
    conn.close()


def test_sse_project_filter(live):
    conn, resp = open_stream(live[1], "/api/events?project=mine")
    read_until(resp, ": connected")
    add(ev("other"), ev("mine", "gate.opened"))
    got = read_until(resp, "gate.opened")
    assert "id: 2" in got and "id: 1\n" not in got
    conn.close()


def test_sse_ping_sent(live):
    conn, resp = open_stream(live[1])
    assert ": ping" in read_until(resp, ": ping")
    conn.close()


def test_sse_survives_rotation(live):
    add(ev(), ev(), ev())
    conn, resp = open_stream(live[1])
    read_until(resp, ": connected")
    paths.events().write_text(json.dumps(ev(type="gate.opened")) + "\n")
    got = read_until(resp, "gate.opened")
    assert "id: 1\nevent: gate.opened" in got
    conn.close()


def test_sse_stream_limit_503(live):
    httpd, port = live
    opened = [open_stream(port) for _ in range(stream.MAX_STREAMS)]
    for _, resp in opened:
        assert resp.status == 200
    conn, resp = open_stream(port)
    assert resp.status == 503
    assert "Too many live views open." in resp.read().decode()
    conn.close()
    for c, _ in opened:
        c.close()


def test_recent_after_line_and_limit(live):
    add(*[ev("a" if i % 2 else "b") for i in range(6)])
    conn, resp = open_stream(live[1], "/api/events/recent?after=2&limit=2")
    data = json.loads(resp.read())["data"]
    assert [e["id"] for e in data["events"]] == [3, 4] and data["next"] == 6
    conn.close()
    conn, resp = open_stream(live[1], "/api/events/recent?limit=2&project=a")
    data = json.loads(resp.read())["data"]
    assert [e["id"] for e in data["events"]] == [4, 6]
    conn.close()


def test_sse_stops_on_server_shutdown(live):
    httpd, port = live
    conn, resp = open_stream(port)
    read_until(resp, ": connected")
    httpd.stopping.set()
    end = time.time() + 3
    while time.time() < end and httpd.streams:
        time.sleep(0.05)
    assert httpd.streams == 0
    conn.close()
