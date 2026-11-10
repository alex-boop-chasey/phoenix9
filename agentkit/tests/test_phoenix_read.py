"""Tests for the Phoenix pack's read tools against a fake Phoenix."""
from agentkit.packs.phoenix import build_pack
from agentkit.packs.phoenix.client import DEFAULT_URL
from agentkit.pack import check_pack
from fake_phoenix import BASE, FakePhoenix


def tools_for(fake):
    pack = build_pack(fake.client())
    return {t.name: t for t in pack.server_tools}


def test_default_address_matches():
    assert DEFAULT_URL == BASE == "http://127.0.0.1:8095"


def test_pack_is_valid_and_all_read():
    pack = build_pack(FakePhoenix().client())
    check_pack(pack)
    assert {t.name: t.risk for t in pack.server_tools if t.name != "set_build_notifications"} == {
        "list_projects": "read", "show_project": "read", "list_runs": "read"}


def test_list_projects_gives_cards_and_sends_header():
    fake = FakePhoenix()
    out = tools_for(fake)["list_projects"].function()
    assert [p["name"] for p in out["projects"]] == ["alpha", "beta"]
    assert out["projects"][0]["link"] == "#/projects/alpha"
    assert set(out["projects"][0]) >= {"name", "status", "last_used", "link"}
    assert fake.requests[0].headers["X-Phoenix"] == "1"


def test_list_projects_passes_filters_through():
    fake = FakePhoenix()
    out = tools_for(fake)["list_projects"].function(q="site", status="idle", owner="alex", sort="modified",
                                                    attention=True)
    assert dict(fake.requests[0].url.params) == {
        "q": "site", "status": "idle", "owner": "alex", "sort": "modified", "attention": "1"}
    assert [p["name"] for p in out["projects"]] == ["alpha"]


def test_show_project():
    out = tools_for(FakePhoenix())["show_project"].function(name="beta")
    assert out["project"]["status"] == "run"
    assert out["project"]["link"] == "#/projects/beta"


def test_list_runs():
    fake = FakePhoenix()
    out = tools_for(fake)["list_runs"].function(name="alpha")
    assert out["runs"][0]["run_id"] == "20261109-1"
    assert fake.requests[0].url.path == "/api/projects/alpha/runs"


def test_refusal_becomes_plain_error():
    out = tools_for(FakePhoenix(refuse=True))["list_projects"].function()
    assert out == {"error": "Refused: the agent isn't allowed to do that."}


def test_missing_project_is_plain_error():
    out = tools_for(FakePhoenix())["show_project"].function(name="nope")
    assert "no project" in out["error"]
