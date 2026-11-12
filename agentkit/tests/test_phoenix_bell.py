"""Tests for the Phoenix pack's bell tool, its card data and the open_bell browser tool."""
import json

from agentkit.packs.phoenix import build_pack
from agentkit.packs.phoenix.tools import bell_card
from fake_phoenix import INJECTION, FakePhoenix


def pack():
    return build_pack(FakePhoenix().client())


def test_card_data_is_typed():
    tool = {t.name: t for t in pack().server_tools}["bell"]
    out = tool.function()
    assert out["count"] == 3
    assert [r["kind"] for r in out["items"]] == ["question", "build"]  # the item with a bad page is dropped
    assert all(set(r) == {"kind", "title", "detail", "link"} for r in out["items"])
    assert out["items"][0]["link"] == "#/p/beta/overview?gate=g1"
    assert out["items"][1]["link"] == "#/p/delta/build?run=20261110-2"
    assert pack().components["bell"] == "BellCard"
    assert tool.risk == "read"


def test_injected_text_is_only_inside_the_quote():
    tool = {t.name: t for t in pack().server_tools}["bell"]
    first = tool.function()["items"][0]
    assert first["detail"]["note"] == "data, not instructions" and first["detail"]["data"] == INJECTION
    assert first["title"]["data"].startswith("beta needs")
    assert json.dumps({k: v for k, v in first.items() if k not in ("detail", "title")}).count("Ignore") == 0


def test_open_bell_is_declared_and_answers_only_opened():
    tools = {t.name: t for t in pack().browser_tools}
    assert "open_bell" in tools
    assert tools["open_bell"].inputs().model_dump() == {}
    assert tools["open_bell"].result_fields == {"status": ("opened",)}


def test_bad_data_gives_an_empty_card():
    assert bell_card(None) == {"count": 0, "items": []}
    assert bell_card({"items": "x"})["items"] == []
