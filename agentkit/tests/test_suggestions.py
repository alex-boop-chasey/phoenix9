"""Tests that suggest_next_actions takes valid items, refuses too many and bad links, and emits one event."""
import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from agentkit import llm, runs, suggest
from agentkit.pack import Pack
from agentkit.store import Store

GOOD = [
    {"label": "Show projects", "message": "List my projects"},
    {"label": "Open dashboard", "link": "#/projects"},
    {"label": "Docs", "link": "https://example.com/docs"},
]


def script(actions, seen):
    """A model that calls suggest_next_actions once, then says it is finished."""

    async def reply(messages, info: AgentInfo):
        turn = sum(1 for m in messages if isinstance(m, ModelResponse))
        seen.append(messages)
        if turn == 0:
            yield {0: DeltaToolCall(name="suggest_next_actions", json_args=json.dumps({"actions": actions}),
                                    tool_call_id="s1")}
        elif turn == 1 and any("not allowed" in str(getattr(p, "content", "")) or "At most" in str(getattr(p, "content", ""))
                               for m in messages for p in getattr(m, "parts", [])):
            yield "I will skip the buttons."
        else:
            yield "All done."

    return FunctionModel(stream_function=reply)


def play(actions):
    """Run one turn with the model offering these actions; return the store and thread id."""

    async def go():
        store, seen, pack = Store(":memory:"), [], Pack(name="t", instructions="")
        r = runs.Runs(store, llm.build_pack_agent(script(actions, seen), pack))
        tid = store.create_thread()["id"]
        r.start(tid, "hi")
        await r.active[tid]
        return store, tid

    return asyncio.run(go())


def events(store, tid):
    """All logged events."""
    return [e for _, e in store.events_after(tid)]


def test_valid_items_are_checked():
    assert suggest.check_actions(GOOD) == GOOD
    assert suggest.check_actions([{"label": "Open", "link": "claude://chat/1"}])
    assert suggest.check_actions([]) == []


def test_more_than_three_refused():
    with pytest.raises(suggest.SuggestionError):
        suggest.check_actions(GOOD + [{"label": "More", "message": "more"}])


@pytest.mark.parametrize("link", [
    "javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,hi", "http://example.com", "ftp://x.org/a",
    "vscode://open", "//evil.example", "/relative", "https://", "#nope", "claude:no-slashes", "#/a b",
])
def test_bad_links_refused(link):
    with pytest.raises(suggest.SuggestionError):
        suggest.check_actions([{"label": "x", "link": link}])


def test_item_needs_exactly_one_of_message_or_link():
    for bad in ({"label": "x"}, {"label": "x", "message": "m", "link": "#/a"}, {"label": "", "message": "m"}):
        with pytest.raises(suggest.SuggestionError):
            suggest.check_actions([bad])


def test_link_schemes_setting_is_used():
    item = [{"label": "x", "link": "myapp://thing"}]
    with pytest.raises(suggest.SuggestionError):
        suggest.check_actions(item)
    assert suggest.check_actions(item, ["myapp"]) == item
    with pytest.raises(suggest.SuggestionError):
        suggest.check_actions([{"label": "x", "link": "javascript://x"}], ["javascript"])


def test_event_comes_at_the_end_of_the_turn_and_never_as_text():
    store, tid = play(GOOD)
    evs = events(store, tid)
    names = [e.get("name") for e in evs if e["type"] == "CUSTOM"]
    assert names.count("suggestions") == 1
    (sug,) = [e for e in evs if e.get("name") == "suggestions"]
    assert sug["value"] == {"actions": GOOD}
    assert evs.index(sug) == len(evs) - 2 and evs[-1]["type"] == "RUN_FINISHED"
    text = "".join(e.get("delta", "") for e in evs if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "Show projects" not in text and "example.com" not in text


def test_refused_items_make_no_event():
    for bad in (GOOD + [GOOD[0]], [{"label": "x", "link": "javascript:alert(1)"}]):
        store, tid = play(bad)
        evs = events(store, tid)
        assert not [e for e in evs if e.get("name") == "suggestions"]
        assert evs[-1]["type"] == "RUN_FINISHED"
