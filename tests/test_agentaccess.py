"""Tests for the agent caller: its uid, its short route list, its settings key, its record and its scrubbed replies."""
import json

from phoenix9 import agentaccess, paths, scrub
from phoenix9.ops import common
from test_api_server import ORIGIN, api, dist, make_project  # noqa: F401  (fixtures)

AGENT_UID = 4242
HEADERS = {"X-Phoenix": "1", "Content-Type": "application/json"}   # no Origin: the agent is not a browser


def write_global(text):
    """Replace global.toml."""
    folder = paths.config()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "global.toml").write_text(text)


def as_agent(api):
    """Make the fake host report the agent's uid for every connection, and turn agent access on."""
    common.make_adapters().host.peer_uid = AGENT_UID
    write_global(f"[agent_next]\nuid = {AGENT_UID}\n")


def test_allowed_routes_work(api):
    make_project("alpha")
    as_agent(api)
    for path in ("/api/projects", "/api/projects/alpha", "/api/projects/alpha/runs", "/api/routes"):
        status, body = api(path, headers=HEADERS)
        assert status == 200 and body["ok"], path
    assert api("/api/routes", headers=HEADERS)[1]["data"][0][0] == "projects"
    status, body = api("/api/projects/alpha/settings", "POST", HEADERS, {"set": {"steps.notify.on": True}})
    assert status == 200 and body["ok"]


def test_route_outside_the_list_is_refused(api):
    make_project("alpha")
    as_agent(api)
    status, body = api("/api/projects/x/delete", "POST", HEADERS, {"yes": True})
    assert status == 403 and "isn't allowed" in body["message"]
    assert api("/api/projects/alpha/keys", headers=HEADERS)[0] == 403
    assert api("/api/projects", "POST", HEADERS, {})[0] == 403
    assert api("/api/info", headers=HEADERS)[0] == 403


def test_needs_the_phoenix_header(api):
    as_agent(api)
    assert api("/api/projects", headers={})[0] == 403


def test_other_settings_key_is_refused(api):
    make_project("alpha")
    as_agent(api)
    for values in ({"merge": "ask"}, {"steps.notify.on": True, "merge": "ask"}, {}):
        status, body = api("/api/projects/alpha/settings", "POST", HEADERS, {"set": values})
        assert status == 403 and "steps.notify.on" in body["message"], values


def test_command_record_says_agent(api):
    make_project("alpha")
    as_agent(api)
    api("/api/projects/alpha/settings", "POST", HEADERS, {"set": {"steps.notify.on": True}})
    lines = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert lines[-1]["who"] == "agent" and lines[-1]["project"] == "alpha"
    log = (paths.projects() / "alpha" / "notes" / "changelog.md")
    assert not log.exists() or "agent" in log.read_text()


def test_planted_secret_is_scrubbed(api):
    folder = make_project("alpha")
    secret = "sk-planted-secret-value-1234567890abcdef"
    scrub.add_secrets([secret])
    (folder / "CLAUDE.md").write_text(f"# alpha\n\nAbout alpha {secret}.\n\n- Profile: python-script\n- Repo: (none yet)\n")
    as_agent(api)
    status, resp, content = api("/api/projects/alpha", headers=HEADERS, raw=True)
    assert status == 200 and secret.encode() not in content
    status, resp, content = api("/api/projects/nope-" + "x", headers=HEADERS, raw=True)
    assert secret.encode() not in content


def test_agent_access_is_off_without_a_uid(api):
    make_project("alpha")
    common.make_adapters().host.peer_uid = AGENT_UID
    assert api("/api/projects", headers=HEADERS)[0] == 403


def test_uid_zero_or_a_peer_uid_is_not_the_agent(api):
    assert "root" in _problem("[agent_next]\nuid = 0\n")
    assert "peer_uids" in _problem("[agent_next]\nuid = 7\n[access]\npeer_uids = [0, 7]\n")
    assert _problem("[agent_next]\nuid = 7\n") == ""


def _problem(text):
    write_global(text)
    from phoenix9 import access
    return agentaccess.uid_problem(access.peer_uids())
