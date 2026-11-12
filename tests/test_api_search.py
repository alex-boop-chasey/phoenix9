"""Tests for search through the API route, the agent's allowlist, the CLI and the generated controls file."""
import json

from helpers.search_seed import SECRET, seed

from phoenix9 import controlsgen
from phoenix9.__main__ import main
from phoenix9.ops import controls
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist  # noqa: F401  (fixtures)


def test_route_returns_typed_results(api):
    seed()
    status, body = api("/api/search?q=zebra")
    assert status == 200 and body["ok"]
    item = body["data"]["results"][0]
    assert (item["kind"], item["project"], item["page"]["to"]) == ("note", "alpha", "doc")
    assert item["page"]["hash"] == "#/doc?path=notes%3Aalpha%2Fideas.md"


def test_kind_and_limit_and_secret(api):
    seed()
    _, body = api("/api/search?q=quokka&kind=log&limit=5")
    assert [r["kind"] for r in body["data"]["results"]] == ["log"]
    assert SECRET not in json.dumps(body)
    assert api("/api/search?q=moon&kind=research")[1]["data"]["results"][0]["kind"] == "research"


def test_bad_query_is_a_400_with_words(api):
    seed()
    for path in ("/api/search?q=", "/api/search?q=a", "/api/search?q=" + "x" * 101, "/api/search?q=ab&kind=zzz",
                 "/api/search?q=ab&limit=x"):
        status, body = api(path)
        assert status == 400 and body["message"], path
    assert "between 2 and 100" in api("/api/search?q=a")[1]["message"]


def test_agent_may_use_only_this_route_for_search(api):
    seed()
    as_agent(api)
    assert api("/api/search?q=zebra", headers=HEADERS)[0] == 200
    assert api("/api/search?q=zebra", "POST", HEADERS, {})[0] in (403, 404, 405)
    assert api("/api/searches?q=zebra", headers=HEADERS)[0] in (403, 404)


def test_cli_plain_and_json(phoenix_env, capsys):
    seed()
    assert main(["search", "zebra"]) == 0
    out = capsys.readouterr().out
    assert "note" in out and "Ideas" in out and "zebra mode" in out
    assert main(["search", "nothing-like-this"]) == 0
    assert "Nothing found." in capsys.readouterr().out
    assert main(["search", "tides", "--kind", "research", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["kind"] == "research"
    assert main(["search", "x"]) != 0


def test_registry_entry_and_generated_file():
    c = {c.name: c for c in controls.CONTROLS}["search"]
    assert (c.risk, c.agent, c.card, c.ops) == ("read", "tool", "search_card", "search.run")
    assert {(i.name, i.where, i.required) for i in c.inputs} == {("q", "query", True), ("kind", "query", False),
                                                                  ("limit", "query", False)}
    names = [e["name"] for e in controlsgen.describe()]
    assert "search" in names
