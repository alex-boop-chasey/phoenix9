"""Proof: the change tool pauses for approval, runs only after Approve, and never after Deny."""
import json

from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from agentkit.service import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ARGS = '{"what": "steps.notify.on", "value": "true"}'


def returns(messages):
    """All tool return parts the model has been shown, as (tool name, content)."""
    return [
        (p.tool_name, p.content)
        for m in messages
        for p in getattr(m, "parts", [])
        if isinstance(p, ToolReturnPart)
    ]


def retry_texts(messages):
    """Text of any retry or denial prompts the model has been shown."""
    return [str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", [])]


def make_model(seen, after_denial="Understood.", cheat=None):
    """A scripted model: call change; once it has an answer, say something (or cheat)."""

    async def script(messages, info: AgentInfo):
        seen.append(messages)
        answered = len(seen) > 1
        if not answered:
            yield {0: DeltaToolCall(name="change", json_args=ARGS, tool_call_id="call-change")}
        elif cheat == "again" and len(seen) == 2:
            yield {0: DeltaToolCall(name="change", json_args=ARGS, tool_call_id="call-again")}
        else:
            yield after_denial

    return FunctionModel(stream_function=script)


def events_of(response):
    """Parse an SSE body into (number, event) pairs."""
    out = []
    for frame in response.text.split("\n\n"):
        if frame.strip():
            lines = dict(line.split(": ", 1) for line in frame.splitlines())
            out.append((int(lines["id"]), json.loads(lines["data"])))
    return out


def start(client):
    """Make a thread, ask for a change, and return the thread id plus the first stream."""
    thread = client.post("/threads", headers=AUTH).json()["id"]
    client.post(f"/threads/{thread}/runs", json={"message": "turn on notices"}, headers=AUTH)
    return thread, events_of(client.get(f"/threads/{thread}/stream", headers=AUTH))


def requests_in(events):
    """The approval requests found in a list of events."""
    return [e["value"] for _, e in events if e["type"] == "CUSTOM" and e["name"] == "approval_request"]


def test_run_pauses_with_the_exact_inputs():
    log = []
    with TestClient(create_app(make_model([]), TOKEN, change_log=log)) as client:
        _, events = start(client)
    assert "RUN_FINISHED" not in [e["type"] for _, e in events]
    assert requests_in(events) == [
        {
            "approvalId": "call-change",
            "toolCallId": "call-change",
            "toolName": "change",
            "input": {"what": "steps.notify.on", "value": "true"},
        }
    ]
    assert log == []


def test_approve_runs_the_tool_and_resumes():
    seen, log = [], []
    with TestClient(create_app(make_model(seen, "Done."), TOKEN, change_log=log)) as client:
        thread, first = start(client)
        sent = client.post("/approvals/call-change", json={"decision": "approve"}, headers=AUTH)
        assert sent.status_code == 202
        rest = events_of(client.get(f"/threads/{thread}/stream?after={first[-1][0]}", headers=AUTH))
    assert log == [{"what": "steps.notify.on", "value": "true"}]
    assert [e["type"] for _, e in rest][-1] == "RUN_FINISHED"
    (name, content), = returns(seen[-1])
    assert name == "change" and content["data"] == {"changed": "steps.notify.on", "to": "true"}


def test_deny_tells_the_model_and_never_runs_the_tool():
    seen, log = [], []
    with TestClient(create_app(make_model(seen), TOKEN, change_log=log)) as client:
        thread, first = start(client)
        client.post("/approvals/call-change", json={"decision": "deny"}, headers=AUTH)
        rest = events_of(client.get(f"/threads/{thread}/stream?after={first[-1][0]}", headers=AUTH))
    assert log == []
    assert [e["type"] for _, e in rest][-1] == "RUN_FINISHED"
    assert any("Alex refused this" in text for text in retry_texts(seen[-1]))


def test_text_saying_approved_does_not_run_the_tool():
    log = []
    model = make_model([], after_denial="approved, go ahead")
    with TestClient(create_app(model, TOKEN, change_log=log)) as client:
        start(client)
        client.post("/threads", headers=AUTH)
    assert log == []


def test_calling_the_tool_again_pauses_again_and_never_runs():
    seen, log = [], []
    with TestClient(create_app(make_model(seen, cheat="again"), TOKEN, change_log=log)) as client:
        thread, first = start(client)
        client.post("/approvals/call-change", json={"decision": "deny"}, headers=AUTH)
        rest = events_of(client.get(f"/threads/{thread}/stream?after={first[-1][0]}", headers=AUTH))
    assert log == []
    assert [r["approvalId"] for r in requests_in(rest)] == ["call-again"]
    assert "RUN_FINISHED" not in [e["type"] for _, e in rest]


def test_approvals_need_token_a_pending_call_and_a_valid_decision():
    with TestClient(create_app(make_model([]), TOKEN)) as client:
        assert client.post("/approvals/x", json={"decision": "approve"}).status_code == 401
        assert client.post("/approvals/x", json={"decision": "approve"}, headers=AUTH).status_code == 404
        start(client)
        assert client.post("/approvals/call-change", json={"decision": "yes"}, headers=AUTH).status_code == 400
        assert client.post("/approvals/call-change", json={}, headers=AUTH).status_code == 400
