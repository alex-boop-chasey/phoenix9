"""Tests for the what_happened tool: card data, and refusal of anything but repair controls."""
from agentkit.packs.phoenix import build_pack
from fake_phoenix import FAILED_RUN, FakePhoenix


def tool():
    pack = build_pack(FakePhoenix().client())
    return {t.name: t for t in pack.server_tools}["what_happened"], pack


def call(options):
    t, _ = tool()
    return t.function(project="beta", run_id=FAILED_RUN, cause="Task 2 ran out of tries.", tried=["Try 1 failed"],
                      suggestion="Allow more tries.", options=options)


def test_what_happened_tool_is_a_read_tool_with_a_card():
    t, pack = tool()
    assert t.risk == "read" and pack.components["what_happened"] == "WhatHappenedCard"


def test_what_happened_tool_returns_card_data():
    opts = [{"label": "Allow 3 tries", "tool": "repair-raise-max-tries",
             "inputs": {"project": "beta", "run_id": FAILED_RUN, "tries": 3}},
            {"label": "Resume", "tool": "build-resume", "inputs": {"run_id": FAILED_RUN}}]
    out = call(opts)
    assert out["cause"].startswith("Task 2") and out["tried"] == ["Try 1 failed"] and out["options"] == opts


def test_what_happened_tool_refuses_other_tools():
    assert "not a repair control" in call([{"label": "x", "tool": "repair-apply", "inputs": {}}])["error"]
    assert "error" in call([{"label": "x", "tool": "project-show", "inputs": {"name": "beta"}}])


def test_what_happened_tool_refuses_bad_inputs():
    out = call([{"label": "Skip", "tool": "repair-skip-task", "inputs": {"project": "beta", "run_id": FAILED_RUN}}])
    assert "not valid" in out["error"]
