"""Tests for the bell through the API route, the agent's allowlist, the CLI and the generated controls file."""
import json

from phoenix9 import controlsgen, gates
from phoenix9.__main__ import main
from phoenix9.ops import controls
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist  # noqa: F401  (fixtures)
from test_status_report import make_project, make_run


def seed():
    make_project()
    gates.open_gate(make_run("r1", "running"), kind="escalation", title="Task 2 failed", why="because")
    make_run("r2", "failed", ago_s=3600, flagged="tests failed")


def test_route_count_equals_items(api):
    seed()
    status, body = api("/api/bell")
    assert status == 200 and body["ok"]
    data = body["data"]
    assert data["count"] == len(data["items"]) >= 2
    assert {"question", "build"} <= {i["kind"] for i in data["items"]}
    assert all(i["page"]["hash"].startswith("#/") for i in data["items"])


def test_agent_may_read_only(api):
    seed()
    as_agent(api)
    assert api("/api/bell", headers=HEADERS)[0] == 200
    assert api("/api/bell", "POST", HEADERS, {})[0] in (403, 404, 405)


def test_cli_one_line_per_item(phoenix_env, capsys):
    seed()
    assert main(["bell"]) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    kinds = [x.split(" · ")[0] for x in lines]
    assert "question" in kinds and "build" in kinds and len(lines) == len(kinds)
    assert main(["bell", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == len(data["items"]) == len(lines)


def test_registry_entry_and_generated_file():
    c = {c.name: c for c in controls.CONTROLS}["bell"]
    assert (c.risk, c.agent, c.card, c.ops) == ("read", "tool", "bell_card", "bell.show")
    assert "bell" in [e["name"] for e in controlsgen.describe()]
