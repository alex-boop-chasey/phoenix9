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
    risks = {t.name: t.risk for t in pack.server_tools}
    assert {n: risks[n] for n in ("projects-list", "project-show", "builds-list")} == {
        "projects-list": "read", "project-show": "read", "builds-list": "read"}


def test_list_projects_gives_cards_and_sends_header():
    fake = FakePhoenix()
    out = tools_for(fake)["projects-list"].function()
    assert [p["name"] for p in out["projects"]] == ["alpha", "beta"]
    assert out["projects"][0]["link"] == "#/p/alpha"
    assert set(out["projects"][0]) >= {"name", "status", "last_used", "link"}
    assert fake.requests[0].headers["X-Phoenix"] == "1"


def test_list_projects_passes_filters_through():
    fake = FakePhoenix()
    out = tools_for(fake)["projects-list"].function(q="site", status="idle", owner="alex", sort="modified",
                                                    attention=True)
    assert dict(fake.requests[0].url.params) == {
        "q": "site", "status": "idle", "owner": "alex", "sort": "modified", "attention": "1"}
    assert [p["name"] for p in out["projects"]] == ["alpha"]


def test_show_project():
    out = tools_for(FakePhoenix())["project-show"].function(name="beta")
    assert out["project"]["status"] == "run"
    assert out["project"]["link"] == "#/p/beta"


def test_list_runs():
    fake = FakePhoenix()
    out = tools_for(fake)["builds-list"].function(name="alpha")
    assert out["runs"][0]["run_id"] == "20261109-1"
    assert fake.requests[0].url.path == "/api/projects/alpha/runs"


def test_refusal_becomes_plain_error():
    out = tools_for(FakePhoenix(refuse=True))["projects-list"].function()
    assert out == {"error": "Refused: the agent isn't allowed to do that."}


def test_missing_project_is_plain_error():
    out = tools_for(FakePhoenix())["project-show"].function(name="nope")
    assert "no project" in out["error"]


def test_the_pack_agent_hands_the_panel_a_card_for_read_tools():
    from agentkit import llm

    fake = FakePhoenix()
    tool = tools_for(fake)["projects-list"]
    made = llm._pack_tool(tool, "project_cards")
    out = made.function()
    assert out.metadata["component"] == "project_cards"
    assert "projects" in out.metadata["data"]
