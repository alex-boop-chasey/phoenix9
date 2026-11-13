"""Tests for the bell through the API route, the agent's allowlist, the CLI and the generated controls file."""
import json
import re

from phoenix9 import controlsgen, gates
from phoenix9.__main__ import main
from phoenix9.ops import controls
from test_agentaccess import HEADERS, as_agent
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)
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


def test_dismiss_route_hides_one_and_answers_the_new_list(api):
    seed()
    before = api("/api/bell")[1]["data"]
    gone = next(i for i in before["items"] if i["kind"] == "build")
    status, body = api("/api/bell/dismiss", "POST", POST_HEADERS, {"id": gone["id"]})
    assert status == 200 and body["ok"]
    data = body["data"]
    assert data["count"] == len(data["items"]) == before["count"] - 1
    assert gone["id"] not in [i["id"] for i in data["items"]]
    assert api("/api/bell")[1]["data"]["count"] == data["count"]


def test_dismiss_unknown_odd_id_is_fine_and_bad_body_is_400(api):
    seed()
    odd = "question:demo:a/b + c:d " + "x" * 3000
    assert api("/api/bell/dismiss", "POST", POST_HEADERS, {"id": odd})[0] == 200
    assert api("/api/bell/dismiss", "POST", POST_HEADERS, {})[0] == 400
    assert api("/api/bell/dismiss", "POST", POST_HEADERS, {"id": 5})[0] == 400


def test_dismiss_all_route_empties_the_bell(api):
    seed()
    status, body = api("/api/bell/dismiss-all", "POST", POST_HEADERS, {})
    assert status == 200 and body["data"] == {"count": 0, "items": []}
    assert api("/api/bell")[1]["data"]["count"] == 0


def test_items_are_dated_newest_first(api):
    seed()
    items = api("/api/bell")[1]["data"]["items"]
    assert all(i["since"] for i in items)
    assert [i["since"] for i in items] == sorted((i["since"] for i in items), reverse=True)


def test_agent_may_not_dismiss(api):
    seed()
    as_agent(api)
    assert api("/api/bell/dismiss", "POST", HEADERS, {"id": "build:demo:r2"})[0] in (403, 404)
    assert api("/api/bell/dismiss-all", "POST", HEADERS, {})[0] in (403, 404)


def test_cli_prints_dates_and_dismisses(phoenix_env, capsys):
    seed()
    assert main(["bell", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)["items"]
    assert main(["bell"]) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert all(re.match(r"\w+ · \d{4}-\d\d-\d\d \d\d:\d\d · ", x) for x in lines)
    assert main(["bell", "dismiss", items[0]["id"]]) == 0
    capsys.readouterr()
    assert main(["bell", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == len(items) - 1
    assert main(["bell", "dismiss", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0
    assert main(["bell", "dismiss"]) == 1


def test_dismiss_controls_are_listed():
    found = {c.name: c for c in controls.CONTROLS}
    assert (found["bell-dismiss"].method, found["bell-dismiss"].route, found["bell-dismiss"].ops) == ("POST", "/api/bell/dismiss", "bell.dismiss")
    assert [i.where for i in found["bell-dismiss"].inputs] == ["body"]
    assert found["bell-dismiss-all"].ops == "bell.dismiss_all"
    assert {"bell-dismiss", "bell-dismiss-all"} <= {e["name"] for e in controlsgen.describe()}
