"""Tests for the next_steps tool: fixed suggestions chosen by rule from a project's state."""
import json

from agentkit.packs.phoenix import build_pack
from fake_phoenix import HOSTILE_TITLE, FakePhoenix


def steps(name):
    tools = {t.name: t for t in build_pack(FakePhoenix().client()).server_tools}
    return tools["next_steps"].function(project=name)


def labels(name):
    return [s["label"] for s in steps(name)["suggestions"]]


def test_no_build_yet():
    assert labels("fresh") == ["Start a build"]


def test_failed_run_and_open_question():
    assert labels("delta") == ["What went wrong?", "Answer the open question"]


def test_run_going():
    assert labels("busy") == ["How is the build doing?"]


def test_otherwise_settings():
    assert labels("alpha") == ["Show me the settings"]


def test_never_more_than_three_and_checked():
    for name in ("fresh", "delta", "busy", "alpha"):
        out = steps(name)["suggestions"]
        assert 1 <= len(out) <= 3
        assert all(set(s) == {"label", "message"} for s in out)


def test_hostile_title_never_appears():
    assert HOSTILE_TITLE not in json.dumps(steps("delta"))
    assert "Ignore" not in json.dumps(steps("delta"))


def test_unknown_project_and_no_data_are_safe():
    assert "error" in steps("nowhere")
    assert "error" in steps("../etc")
    from agentkit.packs.phoenix.next_steps import suggestions
    assert suggestions("x", [{"run_id": "../bad", "status": "failed"}], [])[0]["message"] == "What went wrong with the last build of x?"
    assert suggestions("x", [{"status": 5}], []) == [{"label": "Show me the settings",
                                                       "message": "Show me the settings"}]
