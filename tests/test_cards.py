"""Tests for the card plug-ins, ops.cards, GET /api/cards and `phoenix card`."""
import json

import pytest

from phoenix9 import atomic, cards, paths, state
from phoenix9.__main__ import main
from phoenix9.ops import cards as ops_cards, common
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)

RUN = "20261107-100000-aaaa"


@pytest.fixture
def fake_ops(adapters, monkeypatch):
    """Ops use the fake adapters."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def make_run(project, status="running", run_id=RUN):
    """A run folder with just a state.json."""
    folder = paths.runs(project) / run_id
    folder.mkdir(parents=True)
    st = state.new_state(run_id, project)
    st["status"] = status
    atomic.write_json(folder / "state.json", st)
    return folder


def test_types_and_loading():
    assert cards.types() == ["builds", "chart", "diff", "edits", "gates", "log", "plans", "projects", "prs", "repair", "run", "settings-preview", "table", "update"]
    assert cards.load("nope") is None and cards.load("../x") is None
    assert cards.load("projects").schema["names"] == "list[str]"


@pytest.mark.parametrize("query,word", [
    ({"zzz": 1}, "zzz"), ({"attention": "yes"}, "attention"), ({"names": [1]}, "names"),
    ({"q": 3}, "q"), ([], "object")])
def test_schema_refusal(query, word):
    reason = cards.check_query(cards.load("projects"), query)
    assert reason and word in reason


def test_int_is_not_bool():
    assert cards.check_query(cards.load("builds"), {"limit": True})
    assert cards.check_query(cards.load("builds"), {"limit": 3}) is None


def test_build_refuses(fake_ops):
    with pytest.raises(common.OpsError, match="not a card type"):
        ops_cards.build("nope")
    with pytest.raises(common.OpsError, match="zzz"):
        ops_cards.build("projects", {"zzz": 1})


def test_projects_card(fake_ops):
    make_project("alpha")
    make_project("beta")
    card = ops_cards.build("projects", {"names": ["beta", "alpha", "ghost"]}, "Mine")
    assert card["type"] == "projects" and card["title"] == "Mine" and card["inline"] is False
    assert [r["name"] for r in card["data"]["rest"]] == ["beta", "alpha"]
    assert card["actions"][0] == {"label": "beta", "kind": "route", "route": {"to": "p/beta/overview", "params": {}}}
    assert card["watch"]["types"] == ["project", "run", "gate"] and card["watch"]["projects"] == []
    assert ops_cards.build("projects", {"attention": True})["data"]["top"] == []


def test_gates_card(fake_ops):
    make_project("alpha")
    card = ops_cards.build("gates", {"project": "alpha"})
    assert card["data"] == [] and card["actions"] == [] and card["watch"]["types"] == ["gate"]
    with pytest.raises(common.OpsError):
        ops_cards.build("gates", {"project": "ghost"})


def test_run_card_active_has_stop(fake_ops):
    make_project("alpha")
    make_run("alpha")
    for run_id in (RUN, "latest"):
        card = ops_cards.build("run", {"project": "alpha", "run_id": run_id})
        assert card["data"]["run_id"] == RUN
        open_, stop = card["actions"]
        assert open_["route"] == {"to": "p/alpha/build", "params": {"run": RUN}}
        assert stop["op"] == {"method": "POST", "path": f"/api/runs/alpha/{RUN}/stop", "body": {"confirm": True}}
        assert stop["danger"] is True and stop["confirm"]
        assert card["watch"] == {"projects": ["alpha"], "runs": [RUN], "types": ["run", "step", "task"]}


def test_run_card_finished_has_no_stop(fake_ops):
    make_project("alpha")
    make_run("alpha", "done")
    assert [a["label"] for a in ops_cards.build("run", {"project": "alpha", "run_id": "latest"})["actions"]] == ["Open build"]


def test_run_card_needs_project_and_run(fake_ops):
    make_project("alpha")
    with pytest.raises(common.OpsError):
        ops_cards.build("run", {"project": "alpha"})
    with pytest.raises(common.NotFound):
        ops_cards.build("run", {"project": "alpha", "run_id": "latest"})


def test_builds_card(fake_ops):
    make_project("alpha")
    make_run("alpha", "done", "20261107-100000-aaaa")
    make_run("alpha", "done", "20261107-110000-bbbb")
    card = ops_cards.build("builds", {"project": "alpha", "limit": 1})
    assert len(card["data"]) == 1 and card["watch"]["types"] == ["run"]
    assert len(ops_cards.build("builds", {"project": "alpha"})["data"]) == 2
    for bad in (0, 21):
        with pytest.raises(common.OpsError):
            ops_cards.build("builds", {"project": "alpha", "limit": bad})


def test_api_route(api, fake_ops):
    make_project("alpha")
    q = json.dumps({"names": ["alpha"]})
    status, body = api("/api/cards?type=projects&title=Hi&query=" + q.replace(" ", "%20"))
    assert status == 200 and body["data"]["title"] == "Hi" and body["data"]["data"]["total"] == 1
    assert api("/api/cards?type=projects")[0] == 200
    for path in ("/api/cards?type=projects&query=%7Bnot", "/api/cards?type=nope", "/api/cards?type=projects&query=%7B%22x%22%3A1%7D"):
        status, body = api(path)
        assert status == 400 and body["ok"] is False and body["message"]


def test_cli_plain_output(fake_ops, capsys):
    make_project("alpha")
    assert main(["card", "projects", "--query", '{"attention": true}']) == 0
    lines = capsys.readouterr().out.strip().split("\n")
    assert lines[0] == "0 projects need you" and lines[-1] == lines[0]
    assert lines[1] == "```phoenix-card" and lines[-2] == "```"
    assert json.loads(lines[2]) == {"query": {"attention": True}, "type": "projects", "v": 1}


def test_cli_json_and_errors(fake_ops, capsys):
    make_project("alpha")
    assert main(["card", "projects", "--title", "All", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == "1 project" and out["card"]["title"] == "All" and '"title": "All"' in out["block"]
    assert main(["card", "projects", "--query", "{oops"]) != 0
    assert "JSON" in capsys.readouterr().err
    assert main(["card", "projects", "--query", '{"x": 1}']) != 0
    assert main(["card", "nope"]) != 0
