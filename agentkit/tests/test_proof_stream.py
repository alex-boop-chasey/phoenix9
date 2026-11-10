"""Proof: a scripted model reply arrives in order as AG-UI events over SSE."""
import json

from pydantic_ai.models.function import DeltaToolCalls, FunctionModel
from starlette.testclient import TestClient

from agentkit.service import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CHUNKS = ["Hello", ", ", "Alex."]


async def scripted(messages, info):
    """A fake model that streams its reply in three chunks."""
    for chunk in CHUNKS:
        yield chunk


def read_events(response):
    """Parse an SSE body into (id, event) pairs."""
    pairs = []
    for frame in response.text.split("\n\n"):
        if not frame.strip():
            continue
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        pairs.append((int(lines["id"]), json.loads(lines["data"])))
    return pairs


def run_once(client):
    """Make a thread, post a message and return the stream response."""
    thread = client.post("/threads", headers=AUTH).json()["id"]
    assert client.post(f"/threads/{thread}/runs", json={"message": "hi"}, headers=AUTH).status_code == 202
    return thread, client.get(f"/threads/{thread}/stream", headers=AUTH)


def test_reply_streams_in_order():
    with TestClient(create_app(FunctionModel(stream_function=scripted), TOKEN)) as client:
        _, response = run_once(client)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [e for _, e in read_events(response)]
    types = [e["type"] for e in events]
    assert types == ["RUN_STARTED"] + ["TEXT_MESSAGE_START"] + ["TEXT_MESSAGE_CONTENT"] * 3 + [
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert [e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"] == CHUNKS
    assert len({e["messageId"] for e in events if "messageId" in e}) == 1


def test_stream_can_resume_after_n():
    with TestClient(create_app(FunctionModel(stream_function=scripted), TOKEN)) as client:
        thread, _ = run_once(client)
        rest = read_events(client.get(f"/threads/{thread}/stream?after=3", headers=AUTH))
    assert [n for n, _ in rest] == [4, 5, 6, 7]
    assert rest[0][1]["delta"] == ", "


def test_needs_token():
    with TestClient(create_app(FunctionModel(stream_function=scripted), TOKEN)) as client:
        assert client.post("/threads").status_code == 401
        assert client.get("/threads/x/stream", headers={"Authorization": "Bearer no"}).status_code == 401
