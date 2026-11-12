"""The deployed service, assembled by the same code the systemd entry uses, checked end to end over HTTP."""
import json
import time

from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from agentkit import config, service
from agentkit.store import Store
from fake_phoenix import FakePhoenix

TOKEN = "service-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BRIEF = "Make the Buy button blue on the cart page."
PRICES = {"scripted": {"input_per_mtok": 3.0, "output_per_mtok": 15.0,
                       "cache_read_per_mtok": 0.3, "cache_write_per_mtok": 3.75}}


def scripted(plan, seen=None):
    """A model that makes the planned tool calls one turn at a time, then says it is finished."""

    async def reply(messages, info: AgentInfo):
        turn = sum(1 for m in messages if type(m).__name__ == "ModelResponse")
        if seen is not None:
            seen.append(messages)
        if turn < len(plan):
            name, args = plan[turn]
            yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id=f"call-{turn}")}
        else:
            yield "All done."

    return FunctionModel(stream_function=reply, model_name="scripted")


def make(tmp_path, plan, prices=True, cap=1.0):
    """The real app built through build_service_app with a temp config, the fake Phoenix and a scripted model."""
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    cfg = config.Config(model="scripted", prices=PRICES if prices else {}, monthly_cap_usd=cap,
                        token_file=str(token_file), db_file=str(tmp_path / "db" / "agent.db"))
    fake = FakePhoenix()
    store = Store(cfg.db_file)
    app = service.build_service_app(cfg, TOKEN, scripted(plan), fake.client(), store)
    return TestClient(app), fake, store


def events(client, tid, after=0):
    """The (number, event) pairs on a thread's stream from after N."""
    text = client.get(f"/threads/{tid}/stream?after={after}", headers=AUTH).text
    out = []
    for frame in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in lines:
            out.append((int(lines["id"]), json.loads(lines["data"])))
    return out


def run(client, message="go"):
    """Make a thread, start a run, and wait until its stream stops; return the thread id and events."""
    tid = client.post("/threads", headers=AUTH).json()["id"]
    assert client.post(f"/threads/{tid}/runs", json={"message": message}, headers=AUTH).status_code == 202
    return tid, settle(client, tid)


def settle(client, tid, after=0):
    """Read the stream until the run has finished, errored or paused on a card."""
    for _ in range(300):
        got = events(client, tid, after)
        names = [e.get("name", e["type"]) for _, e in got]
        if {"RUN_FINISHED", "RUN_ERROR", "approval_request"} & set(names):
            return got
        time.sleep(0.02)
    raise AssertionError("the run never settled")


def posts(fake):
    """The change requests (POSTs) the fake Phoenix saw."""
    return [r for r in fake.requests if r.method == "POST"]


def approvals(got):
    """The approval requests in a list of events."""
    return [e["value"] for _, e in got if e["type"] == "CUSTOM" and e.get("name") == "approval_request"]


def test_read_tool_hits_phoenix_and_usage_is_recorded(tmp_path):
    client, fake, store = make(tmp_path, [("projects-list", {})])
    with client:
        tid, got = run(client)
        assert got[-1][1]["type"] == "RUN_FINISHED"
        assert any(r.url.path == "/api/projects" for r in fake.requests)
        assert any(e["type"] == "CUSTOM" and e.get("name") == "component" for _, e in got)
        assert posts(fake) == []
        assert store.usage_since(0)  # tokens were recorded
        reply = client.get("/spend", headers=AUTH)
        body = reply.json()
        assert reply.status_code == 200 and set(body) == {"month", "used_share", "state"}
        assert body["used_share"] > 0 and body["state"] in ("plenty", "low", "used_up")
        assert "usd" not in reply.text.lower() and "$" not in reply.text
        assert [t["id"] for t in client.get("/threads", headers=AUTH).json()["threads"]] == [tid]
        assert client.get(f"/threads/{tid}", headers=AUTH).json()["events"]
        assert client.get("/status", headers=AUTH).json()["running"] is True


def test_change_waits_for_approval_and_posts_once_after_approve(tmp_path):
    client, fake, _ = make(tmp_path, [("hotfix-start", {"name": "beta", "brief": BRIEF})])
    with client:
        tid, got = run(client)
        (req,) = approvals(got)
        assert req["toolName"] == "hotfix-start" and req["input"]["brief"] == BRIEF
        assert fake.hotfixes == [] and posts(fake) == []
        last = got[-1][0]
        assert client.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"}, headers=AUTH).status_code == 202
        after = settle(client, tid, last)
        assert after[-1][1]["type"] == "RUN_FINISHED"
        assert fake.hotfixes == [{"brief": BRIEF}] and len(posts(fake)) == 1
        again = client.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"}, headers=AUTH)
        assert again.status_code == 409 and len(posts(fake)) == 1


def test_deny_posts_nothing(tmp_path):
    client, fake, _ = make(tmp_path, [("hotfix-start", {"name": "beta", "brief": BRIEF})])
    with client:
        tid, got = run(client)
        (req,) = approvals(got)
        client.post(f"/approvals/{req['approvalId']}", json={"decision": "deny"}, headers=AUTH)
        after = settle(client, tid, got[-1][0])
        assert after[-1][1]["type"] == "RUN_FINISHED"
        assert fake.hotfixes == [] and posts(fake) == []


def test_every_route_refuses_a_missing_or_wrong_token(tmp_path):
    client, fake, _ = make(tmp_path, [])
    wrong = {"Authorization": "Bearer nope"}
    calls = [("GET", "/status"), ("GET", "/spend"), ("GET", "/threads"), ("POST", "/threads"),
             ("GET", "/threads/x"), ("POST", "/threads/x/runs"), ("GET", "/threads/x/stream"),
             ("POST", "/threads/x/stop"), ("POST", "/approvals/x"), ("POST", "/browser-results/x")]
    with client:
        for method, path in calls:
            for headers in ({}, wrong):
                assert client.request(method, path, headers=headers, json={}).status_code == 401, (method, path)
    assert fake.requests == []


def test_prices_not_ready_ends_the_run_with_the_plain_refusal(tmp_path):
    client, fake, store = make(tmp_path, [("projects-list", {})], prices=False)
    with client:
        tid, got = run(client)
        last = got[-1][1]
        assert last["type"] == "RUN_ERROR" and last["message"] == config.PRICES_NOT_READY
        assert fake.requests == [] and store.usage_since(0) == []
        assert client.get("/spend", headers=AUTH).status_code == 200


def test_the_database_folder_is_made_and_closed_cleanly(tmp_path):
    client, _, _ = make(tmp_path, [])
    with client:
        assert (tmp_path / "db" / "agent.db").exists()
