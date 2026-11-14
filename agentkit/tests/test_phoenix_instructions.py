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
    # ask_env_file: the browser upload card, the model gets no file content.
    # reference-file-remove: removes one uploaded reference document after a typed confirmation; it writes
    # nothing and cannot touch code (uploading stays Alex's alone).
    allowed = {"ask_env_file", "reference-file-remove",
               "edits-list",    # lists the quick edits project chats started; writes nothing
               "edit-finish",   # finishes a quick edit (checks + merge request); writes no file content
               "edit-abandon",  # throws away a quick edit a project chat started; writes no file content
               "build-note"}    # adds Alex-approved words to a task's next try; writes no code
    for name in names:
        for word in ("write-file", "edit", "file", "patch", "apply", "note"):
            assert name in allowed or word not in name.lower().replace("profiles", ""), name
    assert "repair-apply" not in names


def test_instructions_send_how_questions_to_phoenix_help():
    assert "read phoenix_help first" in INSTRUCTIONS


def test_instructions_explain_a_bell_item_by_its_id():
    assert '"Tell me about bell item <id>", call bell (and suggest-list when that item\'s kind is suggestion)' in INSTRUCTIONS
