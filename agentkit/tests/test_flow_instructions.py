"""Checks the Phoenix instructions for the guided flows name real tools, forbid typed keys and allow cancel."""
from agentkit.packs.phoenix import FLOW_INSTRUCTIONS, INSTRUCTIONS, build_pack
from fake_phoenix import FakePhoenix

TOOLS = (
    "flow", "ask_choice", "project-check-name", "library-profiles", "library-templates", "library-services",
    "project-create", "job-status", "ask_for_key", "ask_env_file", "hotfix-start", "project-specs",
    "build-plan", "build-start", "next_steps", "suggest_next_actions")


def test_flow_instructions_name_every_tool_and_it_exists():
    pack = build_pack(FakePhoenix().client())
    names = {t.name for t in pack.server_tools} | {t.name for t in pack.browser_tools}
    for tool in TOOLS:
        assert tool in FLOW_INSTRUCTIONS, tool
        if tool != "suggest_next_actions":  # added by the loop, not the pack
            assert tool in names, tool


def test_flow_instructions_forbid_typing_keys_and_allow_cancel():
    text = INSTRUCTIONS.lower()
    assert "never ask alex to type a key or paste a .env into the chat" in text
    assert "cancelled" in text and "never mind" in text


def test_flow_instructions_have_no_money():
    text = FLOW_INSTRUCTIONS.lower()
    assert "$" not in INSTRUCTIONS
    for word in ("dollar", "money", "price", "cost", "usd", "cents", "pay"):
        assert word not in text, word
