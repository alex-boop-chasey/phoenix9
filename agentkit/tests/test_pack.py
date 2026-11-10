"""Tests for the site pack interface, using a tiny pack that lives only in the tests folder."""
import sys
import types

import pytest
from pydantic import BaseModel

from agentkit.pack import BrowserTool, Pack, PackError, ServerTool, load_pack


class Echo(BaseModel):
    text: str


class Go(BaseModel):
    path: str


def echo(text: str) -> str:
    return text


def make_pack(**changes) -> Pack:
    fields = dict(
        name="tiny",
        instructions="Be brief.",
        server_tools=(ServerTool("echo", "Echo text", Echo, "read", echo),),
        browser_tools=(BrowserTool("go_to", "Open a page", Go),),
        components={"echo": "EchoCard"},
        settings={},
    )
    fields.update(changes)
    return Pack(**fields)


@pytest.fixture
def install(monkeypatch):
    """Put a module with the given PACK under agentkit.packs.<name> without touching the core."""

    def _install(name, pack):
        module = types.ModuleType(f"agentkit.packs.{name}")
        module.PACK = pack
        monkeypatch.setitem(sys.modules, f"agentkit.packs.{name}", module)

    return _install


def test_loads_a_pack_defined_outside_the_core(install):
    install("tiny", make_pack())
    pack = load_pack("tiny")
    assert pack.name == "tiny"
    assert pack.components == {"echo": "EchoCard"}
    assert pack.server_tools[0].function("hi") == "hi"


def test_duplicate_names_are_refused(install):
    install("dup", make_pack(browser_tools=(BrowserTool("echo", "x", Go),)))
    with pytest.raises(PackError, match="more than once"):
        load_pack("dup")


def test_unknown_risk_is_refused(install):
    bad = ServerTool("echo", "Echo", Echo, "scary", echo)
    install("risk", make_pack(server_tools=(bad,)))
    with pytest.raises(PackError, match="unknown risk"):
        load_pack("risk")


def test_card_for_unknown_tool_is_refused(install):
    install("card", make_pack(components={"ghost": "GhostCard"}))
    with pytest.raises(PackError, match="not a tool"):
        load_pack("card")


def test_missing_pack_says_so():
    with pytest.raises(PackError, match="no site pack"):
        load_pack("nope_not_here")
