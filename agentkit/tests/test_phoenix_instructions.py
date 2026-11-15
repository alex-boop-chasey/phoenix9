"""Checks that the Phoenix pack's instructions cover the full tool set and no delete tool exists."""
import asyncio

from pydantic_ai.models.function import AgentInfo, FunctionModel

from agentkit import llm, runs
from agentkit.packs.phoenix import FLOW_INSTRUCTIONS, INSTRUCTIONS, build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix
from test_browser_tools import customs


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


def test_instructions_send_a_repeat_to_run_again():
    assert ("To repeat a failed or stopped build as it was, use run-again (not build-start); "
            "use repair-restart-preset only to change the preset as a repair.") in INSTRUCTIONS


def test_handoff_paragraph_says_act_alone_through_the_two_tools():
    for words in (
        "a message starting [Phoenix · escalation] is a build task Phoenix handed to you",
        "read (run-diagnose, task-tries, run-events, step-session); decide the cause",
        "handoff-fix action retry (with a short note for the builder",
        "handoff-fix action rewrite-checks with the evidence in why (once per task)",
        "Phoenix tells you how it ends",
        "Never skip, stop, change settings or budgets, merge, or touch other runs or tasks",
        "call handoff-give-up with the reason",
        "These two tools need no card in a hand-off conversation; everything else does.",
        "Do not ask Alex questions in a hand-off conversation; he reads it later.",
    ):
        assert words in INSTRUCTIONS, words
    for old in ("only after Alex approved", "only answer you may give is acknowledged",
                "leave the question for Alex"):
        assert old not in INSTRUCTIONS, old


CANT = "I can't do that yet; it isn't one of my tools. You can look for travel in your browser instead."


def test_instructions_say_plainly_when_no_tool_fits():
    for words in ("say so in one plain line", "and stop", "never repeat the same options again",
                  "never pretend", "never ask him to type commands", "offer go_to"):
        assert words in INSTRUCTIONS.lower(), words
    assert "the flow card's own Cancel still applies" in INSTRUCTIONS


def test_flow_keys_line_says_keys_make_or_cannot_yet():
    keys = next(line for line in FLOW_INSTRUCTIONS.splitlines() if line.startswith("Keys:"))
    assert "get or make the keys for him, use keys-make when it is there" in keys
    assert "say plainly in one line that you can't do that yet" in keys


def test_unknown_request_gets_one_plain_line_and_no_card():
    async def go():
        seen = []

        async def reply(messages, info: AgentInfo):
            seen.append(messages)
            yield CANT

        store = Store(":memory:")
        pack = build_pack(FakePhoenix().client())
        r = runs.Runs(store, llm.build_pack_agent(FunctionModel(stream_function=reply), pack), pack)
        tid = store.create_thread()["id"]
        r.start(tid, "book me a flight")
        await r.active[tid]
        events = [e for _, e in store.events_after(tid)]
        kinds = [e["type"] for e in events]
        assert kinds.count("TEXT_MESSAGE_START") == 1 and kinds[-1] == "RUN_FINISHED"
        assert "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT") == CANT
        assert not any(k.startswith("TOOL_CALL") for k in kinds)
        assert customs(store, tid, "browser_tool") == []
        assert len(seen) == 1

    asyncio.run(go())
