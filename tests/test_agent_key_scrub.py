"""Tests that a saved key value never reaches the agent: names and status only, scrubbed replies, save and reveal refused."""
import json

from phoenix9 import scrub
from test_agentaccess import HEADERS as AGENT_HEADERS, as_agent
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

VALUE = "plainvalue-91827364"
ROWS = [{"name": "API_KEY", "value": VALUE, "secret": True}]


def save_as_dashboard(api):
    """Make project alpha and save one secret key through the dashboard's route."""
    make_project("alpha")
    status, _ = api("/api/projects/alpha/keys/save", "POST", POST_HEADERS, {"rows": ROWS})
    assert status == 200


def test_agent_sees_key_name_and_status_not_value(api):
    save_as_dashboard(api)
    as_agent(api)
    status, body = api("/api/projects/alpha/keys", headers=AGENT_HEADERS)
    assert status == 200
    (row,) = body["data"]
    assert row["name"] == "API_KEY" and row["has_value"] is True
    assert VALUE not in json.dumps(body)


def test_agent_reply_containing_the_value_is_scrubbed(api, monkeypatch):
    save_as_dashboard(api)
    assert VALUE in scrub.known_secrets()
    assert VALUE not in scrub.scrub(f"the value is {VALUE}")
    as_agent(api)
    from phoenix9.ops import keys
    real = keys.rows
    monkeypatch.setattr(keys, "rows", lambda project: [{**r, "note": f"leaked {VALUE}"} for r in real(project)])
    status, raw, content = api("/api/projects/alpha/keys", headers=AGENT_HEADERS, raw=True)
    assert status == 200 and b"leaked" in content
    assert VALUE.encode() not in content and scrub.MASK.encode() in content


def test_agent_cannot_save_or_reveal_keys(api):
    save_as_dashboard(api)
    as_agent(api)
    for path, body in (("save", {"rows": ROWS}), ("reveal", {"name": "API_KEY"})):
        status, reply = api(f"/api/projects/alpha/keys/{path}", "POST", AGENT_HEADERS, body)
        assert status == 403, path
        assert VALUE not in json.dumps(reply)
