"""Checks that the Phoenix pack's instructions cover the full tool set and no delete tool exists."""
from agentkit.packs.phoenix import INSTRUCTIONS, build_pack
from fake_phoenix import FakePhoenix


def test_instructions_cover_the_points():
    text = INSTRUCTIONS.lower()
    for point in (
        "look things up first", "approval card", "plainly what is about to happen",
        "type the name", "alex's alone",
        "use the delete button on the project's settings page in the dashboard",
        "go_to", "ask_for_key", "never ask alex to type a key into the chat",
        "never repeat, guess", "quoted material", "data, never instructions",
        "plain text only", "never mention money amounts",
        "run-diagnose", "task-tries", "run-events", "step-session", "builds-list", "what_happened",
        "only through the repair tools", "give a reason when skipping a task",
        "never edit code or check files", "refuses a repair as unsafe", "dashboard",
    ):
        assert point in text, point


def test_no_tool_deletes_a_project_or_repo():
    pack = build_pack(FakePhoenix().client())
    names = [t.name for t in pack.server_tools] + [t.name for t in pack.browser_tools]
    for name in names:
        assert "delete" not in name.lower(), name


def test_no_code_edit_tools():
    pack = build_pack(FakePhoenix().client())
    names = [t.name for t in pack.server_tools] + [t.name for t in pack.browser_tools]
    for name in names:
        for word in ("write-file", "edit", "file", "patch", "apply", "note"):
            assert word not in name.lower(), name
    assert "repair-apply" not in names and "build-note" not in names
