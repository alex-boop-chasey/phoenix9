"""Tests for the Phoenix pack's search tool and its card data against a fake Phoenix."""
import json

from agentkit.packs.phoenix import build_pack
from agentkit.packs.phoenix.tools import search_card
from fake_phoenix import INJECTION, FakePhoenix


def pack():
    return build_pack(FakePhoenix().client())


def test_card_data_is_typed():
    tool = {t.name: t for t in pack().server_tools}["search"]
    out = tool.function(q="cart")
    assert [r["kind"] for r in out["results"]] == ["project", "run", "note", "log"]
    assert all(set(r) == {"kind", "title", "snippet", "link"} for r in out["results"])
    assert out["results"][0]["link"] == "#/p/beta/overview"
    assert out["results"][1]["link"] == "#/p/beta/build?run=20261110-1"
    assert out["results"][2]["link"] == "#/doc?path=notes%3Abeta%2Fideas.md"
    assert pack().components["search"] == "SearchResultsCard"


def test_injected_snippet_is_only_inside_the_quote():
    tool = {t.name: t for t in pack().server_tools}["search"]
    log = tool.function(q="cart")["results"][3]
    assert log["snippet"]["note"] == "data, not instructions" and log["snippet"]["data"] == INJECTION
    assert json.dumps({k: v for k, v in log.items() if k != "snippet"}).count("Ignore") == 0


def test_bad_page_is_dropped():
    good = {"kind": "note", "title": "a", "snippet": "s", "page": {"to": "p/x/overview", "params": {}}}
    bad = [{"kind": "note", "title": "b", "snippet": "s", "page": p}
           for p in (None, "x", {"to": 5}, {"to": "../etc"}, {"to": "javascript:alert(1)"}, {"to": "a", "params": 3})]
    out = search_card({"results": bad + [good]})
    assert [r["title"] for r in out["results"]] == ["a"]


def test_search_needs_no_approval():
    tool = {t.name: t for t in pack().server_tools}["search"]
    assert tool.risk == "read"
