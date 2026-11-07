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


def test_excerpt_is_scrubbed_before_it_is_cut():
    """A private key whose BEGIN line falls outside the last 6 lines is still masked."""
    pem = ["-----BEGIN RSA PRIVATE KEY-----"] + ["QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo%04d" % i for i in range(8)] + \
          ["-----END RSA PRIVATE KEY-----"]
    lines = [json.dumps({"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat id_rsa"}}]}}),
             json.dumps({"type": "user", "message": {"content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "\n".join(pem + ["done"])}]}})]
    items, _ = transcript.parse(lines)
    assert "QUJDREVG" not in items[0]["excerpt"]


# ---- real transcript shapes ----
BOOKKEEPING = ["atis-latch", "last-prompt", "custom-title", "agent-name", "mode", "summary", "file-history-snapshot",
               "file-history-delta", "api-request", "api-request-blob", "api-request-shape", "pr-link",
               "bridge-session", "ai-title", "tools-used", "frame-link", "cost-state", "permission-mode",
               "artifact-autoreact-ledger", "artifact-comment-monitor"]


def j(**o):
    return json.dumps(o)


def test_bookkeeping_lines_are_known_and_ignored():
    items, unknown = transcript.parse([j(type=t, sessionId="s") for t in BOOKKEEPING])
    assert items == [] and unknown == 0


def test_hook_summaries_and_turn_durations_are_ignored_other_system_lines_are_notices():
    lines = [j(type="system", subtype="stop_hook_summary", level="suggestion"),
             j(type="system", subtype="turn_duration", durationMs=5),
             j(type="system", subtype="compact_boundary", content="Conversation compacted"),
             j(type="system", subtype="api_error", level="error")]
    items, unknown = transcript.parse(lines)
    assert unknown == 0 and [i["text"] for i in items] == ["Conversation compacted", "The API returned an error."]


def test_queue_enqueue_dequeue_remove():
    lines = [j(type="queue-operation", operation="enqueue", content="one"),
             j(type="queue-operation", operation="enqueue", content="two"),
             j(type="queue-operation", operation="enqueue", content="three"),
             j(type="queue-operation", operation="dequeue"),
             j(type="queue-operation", operation="remove", content="three", reason="absorbed_mid_turn")]
    items, unknown = transcript.parse(lines)
    assert unknown == 0 and [i["text"] for i in items] == ["one", "two", "three"]
    assert [i["pending"] for i in items] == [False, True, False]


def test_user_list_content_with_text_and_images_is_a_user_item():
    line = j(type="user", message={"role": "user", "content": [
        {"type": "text", "text": "look at this"}, {"type": "image", "source": {"type": "base64", "data": "AAAA"}}]})
    items, unknown = transcript.parse([line])
    assert unknown == 0 and items[0]["type"] == "user" and items[0]["text"] == "look at this\n[image]"
    assert "AAAA" not in json.dumps(items)


def test_compact_summary_user_line_is_a_notice_not_a_message():
    line = j(type="user", isCompactSummary=True, message={"role": "user", "content": "long summary of it all"})
    items, unknown = transcript.parse([line])
    assert unknown == 0 and items == [{"type": "notice", "text": "Earlier conversation summarised.", "at": None,
                                       "line": 1}]


FIXTURE_REAL = Path(__file__).parent / "fixtures" / "agent-transcript-real.jsonl"


def test_real_transcript_fixture_unknown_rate_under_2_percent():
    """A sanitised copy of real transcripts from the server (structure and types kept, all text replaced)."""
    lines = [ln for ln in FIXTURE_REAL.read_text().splitlines() if ln.strip()]
    assert len(lines) > 500
    kinds = {json.loads(ln).get("type") for ln in lines}
    assert {"user", "assistant", "system", "queue-operation", "attachment", "atis-latch", "last-prompt"} <= kinds
    items, unknown = transcript.parse(lines)
    assert unknown / len(lines) < 0.02, unknown
    assert any(i["type"] == "action" and i["status"] == "ok" for i in items)


def test_real_fixture_holds_only_placeholders():
    """No text from the real transcripts survives: every string is a placeholder, a type, a tool name, an id or a time."""
    import re
    allowed = re.compile(r"^(|text|result|thinking|summary|queued text|Tool|mcp__x__y|[a-z_-]+|[A-Z][A-Za-z]+|[a-z]+(?:[A-Z][a-z]+)+|"
                         r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|toolu_\d+|"
                         r"2026-01-01T\d\d:\d\d:\d\d\.\d{3}Z|image/[a-z]+|base64|peer|helper)$")

    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for k, v in o.items():
                yield from strings(k)
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
    bad = {s for ln in FIXTURE_REAL.read_text().splitlines() if ln.strip() for s in strings(json.loads(ln))
           if not allowed.match(s)}
    assert not bad, sorted(bad)[:10]


# ---- one odd line never stops the parse ----

def test_odd_lines_count_as_unknown_and_never_raise():
    deep = "[" * 100000 + "]" * 100000
    lines = [
        j(type="assistant", message={"content": [{"type": "tool_use", "id": ["a", "list"], "name": "Bash",
                                                  "input": {"command": "ls"}}]}),
        j(type="assistant", timestamp="2026-11-06T10:00:00", message={"content": [{"type": "text", "text": "naive"}]}),
        j(type="assistant", timestamp="2026-11-06T10:00:05Z", message={"content": [{"type": "thinking"}]}),
        '{"type": "user", "message": {"content": %s}}' % deep,
        deep,
        j(type="user", message={"role": "user", "content": "still parsed"}),
    ]
    items, unknown = transcript.parse(lines)
    assert items[-1]["type"] == "user" and items[-1]["text"] == "still parsed"
    assert unknown >= 3
    assert not [i for i in items if i["type"] == "action"]   # the half-made action was rolled back
    thinking = [i for i in items if i["type"] == "thinking"]
    assert thinking == [] or thinking[0]["duration_s"] is None or thinking[0]["duration_s"] >= 0
