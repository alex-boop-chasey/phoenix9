"""Proof: card data in the stream, the pause at go_to, and the resume with the browser's result."""
import json

from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from agentkit.service import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PROJECTS = [{"name": "alpha", "state": "idle"}]


def returned(messages, tool):
    """The newest tool return for a tool name in the model's input, or None."""
    for message in reversed(messages):
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart) and part.tool_name == tool:
                return part.content
    return None


def make_model(seen):
    """A scripted model: list projects, then go_to, then say it is done."""

    async def script(messages, info: AgentInfo):
        seen.append(messages)
        if returned(messages, "go_to") is not None:
            yield "Opened it."
        elif returned(messages, "list_projects") is not None:
            yield {0: DeltaToolCall(name="go_to", json_args='{"page": "projects"}', tool_call_id="call-go")}
        else:
            yield {0: DeltaToolCall(name="list_projects", json_args="{}", tool_call_id="call-list")}

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
    """Make a thread, ask something, and return the thread id plus the first stream."""
    thread = client.post("/threads", headers=AUTH).json()["id"]
    client.post(f"/threads/{thread}/runs", json={"message": "open projects"}, headers=AUTH)
    return thread, events_of(client.get(f"/threads/{thread}/stream", headers=AUTH))


def test_card_data_travels_in_the_stream():
    seen = []
    app = create_app(make_model(seen), TOKEN, projects=lambda: PROJECTS)
    with TestClient(app) as client:
        _, events = start(client)
    cards = [e["value"] for _, e in events if e["type"] == "CUSTOM" and e["name"] == "component"]
    assert cards == [
        {"toolCallId": "call-list", "component": "project_cards", "data": {"projects": PROJECTS}}
    ]


def test_run_pauses_at_go_to():
    app = create_app(make_model([]), TOKEN, projects=lambda: PROJECTS)
    with TestClient(app) as client:
        _, events = start(client)
    types = [e["type"] for _, e in events]
    assert "RUN_FINISHED" not in types
    starts = [e for _, e in events if e["type"] == "TOOL_CALL_START"]
    assert [s["toolCallName"] for s in starts] == ["list_projects", "go_to"]
    args = [e["delta"] for _, e in events if e["type"] == "TOOL_CALL_ARGS"]
    assert json.loads(args[-1]) == {"page": "projects"}


def test_browser_result_resumes_and_reaches_the_model():
    seen = []
    app = create_app(make_model(seen), TOKEN, projects=lambda: PROJECTS)
    with TestClient(app) as client:
        thread, first = start(client)
        sent = client.post("/browser-results/call-go", json={"result": {"page": "projects", "ok": True}}, headers=AUTH)
        assert sent.status_code == 202
        rest = events_of(client.get(f"/threads/{thread}/stream?after={first[-1][0]}", headers=AUTH))
    assert [e["type"] for _, e in rest][-1] == "RUN_FINISHED"
    assert "Opened it." in [e.get("delta") for _, e in rest]
    got = returned(seen[-1], "go_to")
    assert got["quoted_from"] == "the browser"
    assert got["data"] == {"page": "projects", "ok": True}
    assert returned(seen[-1], "list_projects")["quoted_from"] == "phoenix projects"


def test_browser_result_needs_token_and_a_pending_call():
    with TestClient(create_app(make_model([]), TOKEN)) as client:
        assert client.post("/browser-results/x", json={"result": 1}).status_code == 401
        assert client.post("/browser-results/x", json={"result": 1}, headers=AUTH).status_code == 404


def test_go_to_is_declared_by_the_server():
    seen_tools = []

    async def script(messages, info: AgentInfo):
        seen_tools.extend(t.name for t in info.function_tools)
        yield "ok"

    with TestClient(create_app(FunctionModel(stream_function=script), TOKEN)) as client:
        start(client)
    assert sorted(set(seen_tools)) == ["change", "go_to", "list_projects"]
