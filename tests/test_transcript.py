"""Tests for the transcript parser."""
import json
from pathlib import Path

from phoenix9 import scrub, transcript

FIXTURE = Path(__file__).parent / "fixtures" / "agent-transcript.jsonl"
SECRET = "sk-test-Zq8vN3pL7xR2mK9d"


def parsed():
    """Parse the fixture with the secret registered."""
    scrub.add_secrets([SECRET])
    return transcript.parse(FIXTURE.read_text().splitlines())


def of(items, kind):
    """Items of one type."""
    return [i for i in items if i["type"] == kind]


def test_users_and_origins():
    items, _ = parsed()
    users = of(items, "user")
    assert [u["origin"] for u in users] == ["panel", "app", "peer:helper-7"]
    assert users[0]["text"] == "status please"
    assert users[2]["text"] == "hello from helper"
    assert all("meta noise" not in u["text"] for u in users)


def test_unknown_counted_attachment_not():
    _, unknown = parsed()
    assert unknown == 2


def test_actions_and_results():
    items, _ = parsed()
    a = {i["id"]: i for i in of(items, "action")}
    assert a["t1"]["title"] == "cat .env" and a["t1"]["status"] == "ok"
    assert len(a["t1"]["excerpt"].splitlines()) == 6 and "[secret]" in a["t1"]["excerpt"]
    assert a["t2"]["title"] == "/a/b.txt" and a["t2"]["status"] == "error" and a["t2"]["excerpt"] == "nope"
    assert a["t3"]["title"] == "message to helper-7" and a["t3"]["status"] == "running"


def test_secret_and_thinking_never_leak():
    items, _ = parsed()
    dump = json.dumps(items)
    assert SECRET not in dump and "pondering" not in dump
    assert len(of(items, "thinking")) == 1


def test_other_items_and_session_divider():
    items, _ = parsed()
    assert of(items, "queued")[0]["text"] == "do it next"
    assert of(items, "notice")[0]["text"] == "Context compacted"
    assert [s["session_id"] for s in of(items, "session")] == ["s2"]
    assert of(items, "agent")[0]["markdown"] == "Checking the env."


def test_line_numbers():
    items, _ = parsed()
    assert of(items, "user")[0]["line"] == 1
    assert of(items, "queued")[0]["line"] == 8
    assert all(isinstance(i["line"], int) for i in items)
