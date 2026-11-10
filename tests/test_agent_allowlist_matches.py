"""Tests that the agent's allowlist is exactly the description file's tool routes, and that its leash holds."""
import json

from phoenix9 import agentaccess, controlsgen
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)

ALPHA = "/api/projects/alpha"


def test_allowlist_equals_the_tool_routes_in_the_description_file():
    entries = json.loads(controlsgen.PATH.read_text())
    tools = {(e["method"], e["route"]) for e in entries if e["agent"] == "tool"}
    assert set(agentaccess.ALLOWED) == tools


def test_delete_routes_are_not_on_the_allowlist():
    for method, route in agentaccess.ALLOWED:
        assert not route.endswith(("/delete", "/delete-repo", "/keys/save", "/keys/reveal")), route
    assert not agentaccess.route_allowed("POST", f"{ALPHA}/delete")
    assert not agentaccess.route_allowed("POST", f"{ALPHA}/delete-repo")


def test_non_tool_routes_are_refused_through_the_api(api):
    make_project("alpha")
    as_agent(api)
    for entry in json.loads(controlsgen.PATH.read_text()):
        if entry["agent"] == "tool":
            continue
        path = entry["route"].replace("(?P<name>[^/]+)", "alpha")
        if "(?P" in path or agentaccess.route_allowed(entry["method"], path):
            continue   # (a fixed path such as check-name can also fit an allowed pattern)
        status, _ = api(path, entry["method"], HEADERS, {} if entry["method"] == "POST" else None)
        assert status == 403, entry["name"]
    for path in ("delete", "delete-repo", "keys/save", "keys/reveal"):
        assert api(f"{ALPHA}/{path}", "POST", HEADERS, {"yes": True})[0] == 403, path


def test_safety_key_change_is_refused(api):
    make_project("alpha")
    as_agent(api)
    status, body = api(f"{ALPHA}/settings", "POST", HEADERS, {"set": {"steps.verify.on": False}})
    assert status == 403 and "safety" in body["message"]


def test_preset_in_the_settings_is_refused(api):
    make_project("alpha")
    as_agent(api)
    status, body = api(f"{ALPHA}/settings", "POST", HEADERS, {"set": {"preset": "simple"}})
    assert status == 403 and "preset" in body["message"]


def test_safety_changing_preset_is_refused(api):
    make_project("alpha")
    as_agent(api)
    status, body = api(f"{ALPHA}/settings/preset", "POST", HEADERS, {"preset": "simple"})
    assert status == 403 and "Refused" in body["message"]


def test_edit_may_only_set_services(api):
    make_project("alpha")
    as_agent(api)
    for body in ({"description": "x"}, {"repo": "a/b", "confirm": True}, {"services": [], "profile": "x"}):
        status, reply = api(f"{ALPHA}/edit", "POST", HEADERS, body)
        assert status == 403 and "services" in reply["message"], body


def test_routes_page_list_stays_reachable(api):
    as_agent(api)
    assert api("/api/routes", headers=HEADERS)[0] == 200
