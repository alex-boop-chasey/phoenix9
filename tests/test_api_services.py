"""The services endpoints: list, connect (write guard, no logging or echo of values), disconnect, audit."""
import json

from phoenix9 import paths
from phoenix9.ops import common
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

SENTINEL = "sk-SENTINEL-123"
CHECK_URL = "http://proxy.fake/supabase/v1/projects"


def test_get_services(api):
    status, body = api("/api/services")
    rows = {r["name"]: r for r in body["data"]["services"]}
    assert status == 200 and body["data"]["supported"] is True and len(rows) == 9
    assert rows["supabase"]["endpoints"] == {"connect": "services/supabase/connect",
                                             "disconnect": "services/supabase/disconnect"}
    assert rows["supabase"]["connected"] is False and rows["stripe"]["connected"] is True
    assert api("/api/keys/audit")[1]["data"]["problems"] == []


def test_connect_needs_write_guard(api):
    body = {"values": {"SUPABASE_ACCESS_TOKEN": SENTINEL}}
    assert api("/api/services/supabase/connect", "POST", {"Content-Type": "application/json"}, body)[0] == 403
    assert not (paths.secrets() / "service-supabase.env").exists()


def test_connect_body_never_logged_or_echoed(api, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    status, body = api("/api/services/supabase/connect", "POST", POST_HEADERS,
                       {"values": {"SUPABASE_ACCESS_TOKEN": SENTINEL}})
    assert status == 200 and body["data"]["checked"] == "ok"
    assert SENTINEL not in json.dumps(body)
    bad, bad_body = api("/api/services/supabase/connect", "POST", POST_HEADERS,
                        {"values": {"WRONG": SENTINEL}})
    assert bad == 400 and SENTINEL not in json.dumps(bad_body)
    assert api("/api/services/supabase/connect", "POST", POST_HEADERS, {"values": {"A": 5}})[0] == 400
    seen = (paths.logs() / "api.log").read_text() + (paths.logs() / "commands.jsonl").read_text()
    seen += "".join(p.read_text() for p in paths.events().rglob("*") if p.is_file()) if paths.events().exists() else ""
    assert SENTINEL not in seen


def test_disconnect_requires_yes(api, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    api("/api/services/supabase/connect", "POST", POST_HEADERS, {"values": {"SUPABASE_ACCESS_TOKEN": SENTINEL}})
    assert api("/api/services/supabase/disconnect", "POST", POST_HEADERS, {})[0] == 400
    assert (paths.secrets() / "service-supabase.env").exists()
    status, body = api("/api/services/supabase/disconnect", "POST", POST_HEADERS, {"yes": True})
    assert status == 200 and body["data"]["connected"] is False
    assert not (paths.secrets() / "service-supabase.env").exists()


def test_services_supported_flag_true(api):
    assert api("/api/info")[1]["data"]["services"]["supported"] is True
    assert api("/api/global")[1]["data"]["supported"]["services"] is True
