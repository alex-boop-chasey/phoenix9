"""Tests for the hotfix route called as the agent."""
from phoenix9 import events, paths, runs as runs_core
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)


def test_agent_starts_a_hotfix_and_the_run_records_agent(api):
    make_project("alpha")
    as_agent(api)
    status, body = api("/api/projects/alpha/hotfix", "POST", HEADERS, {"brief": "Fix the typo"})
    assert status == 200, body
    run_id = body["data"]["run_id"]
    assert runs_core.find_run(run_id).is_dir()
    commands = [e for e in events.read(paths.events()) if e.get("type") == "command"]
    assert commands and all(e["data"]["who"] == "agent" for e in commands)
    assert any("run hotfix alpha" in e["data"]["command"] for e in commands)


def test_hotfix_route_refuses_an_empty_brief(api):
    make_project("alpha")
    as_agent(api)
    assert api("/api/projects/alpha/hotfix", "POST", HEADERS, {"brief": " "})[0] == 400
