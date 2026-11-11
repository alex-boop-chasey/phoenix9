"""Tests for the flow tool: card data, refused secrets and nesting, and no Phoenix call."""
from agentkit.packs.phoenix import build_pack
from fake_phoenix import FakePhoenix


def setup():
    fake = FakePhoenix()
    pack = build_pack(fake.client())
    return fake, pack, {t.name: t for t in pack.server_tools}["flow"]


def call(tool, **over):
    args = {"flow": "new-project", "status": "active", "step": 2, "steps": 5, "label": "Pick a type",
            "values": {"name": "demo", "libraries": ["a", "b"], "public": True, "n": 3}}
    return tool.function(**{**args, **over})


def test_flow_tool_active_step_returns_card_data():
    _, pack, tool = setup()
    out = call(tool)
    assert out["flow"] == "new-project" and out["step"] == 2 and out["steps"] == 5
    assert out["values"]["name"] == "demo" and pack.components["flow"] == "FlowCard"


def test_flow_tool_refuses_secret_names_and_nesting():
    _, _, tool = setup()
    for name in ("api_key", "my_Secret", "token", "password", "value"):
        assert "error" in call(tool, values={name: "x"})
    assert "error" in call(tool, values={"a": {"b": 1}})
    assert "error" in call(tool, values={"a": [{"b": 1}]})


def test_flow_tool_refuses_long_value_and_too_many():
    _, _, tool = setup()
    assert "error" in call(tool, values={"a": "x" * 201})
    assert "error" in call(tool, values={"a": ["x" * 201]})
    assert "error" in call(tool, values={f"n{i}": 1 for i in range(13)})
    assert "error" not in call(tool, values={"a": "x" * 200})


def test_flow_tool_accepts_done_and_cancelled():
    _, _, tool = setup()
    assert call(tool, status="done")["status"] == "done"
    assert call(tool, status="cancelled")["status"] == "cancelled"
    assert "error" in call(tool, status="paused")


def test_flow_tool_is_read_and_calls_no_phoenix_route():
    fake, _, tool = setup()
    assert tool.risk == "read"
    call(tool)
    assert fake.requests == []
