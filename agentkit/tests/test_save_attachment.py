"""Tests for offer_save_attachment: a browser card Alex presses; only files of this conversation, results cut down."""
import asyncio
import json

from agentkit import llm, runs
from agentkit.packs.phoenix import INSTRUCTIONS, build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix
from starlette.applications import Starlette
from starlette.routing import Route
from test_browser_tools import client, customs, model_text, script, types

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def build(plan, store):
    """Runs and app around the real Phoenix pack, on this store."""
    seen, pack = [], build_pack(FakePhoenix().client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
    return r, app, seen


async def settle(r, tid):
    """Wait until the thread has no run going."""
    for _ in range(100):
        if tid not in r.active:
            return
        await r.active[tid]


def components(store, tid):
    """The component events logged so far."""
    return customs(store, tid, "component")


def test_the_tool_is_a_browser_tool_with_its_card_and_words():
    pack = build_pack(FakePhoenix().client())
    tool = next(t for t in pack.browser_tools if t.name == "offer_save_attachment")
    assert "offer_save_attachment" not in {t.name for t in pack.server_tools}
    assert tool.description == ("Offer to save a file Alex attached into a project's reference documents. Alex sees "
                                "the file and the project and presses Save himself; you only learn saved, cancelled "
                                "or refused.")
    assert tool.result_fields == {"status": ("saved", "cancelled", "refused"),
                                  "reason": ("too-big", "wrong-type", "exists", "other")}
    assert set(tool.inputs.model_json_schema()["properties"]) == {"attachment_id", "project"}
    assert pack.components["offer_save_attachment"] == "SaveAttachmentCard"
    assert "reference-file-add" not in {t.name for t in pack.server_tools}
    assert "Use offer_save_attachment only when Alex asks to keep a file" in INSTRUCTIONS
    assert "never call it on your own" in INSTRUCTIONS


def test_a_file_of_this_conversation_pauses_with_a_card():
    async def go():
        store = Store(":memory:")
        tid = store.create_thread()["id"]
        pic = store.add_attachment(tid, "mock up.png", "image/png", PNG)
        r, _app, _seen = build([("offer_save_attachment", {"attachment_id": pic["id"], "project": "demo"})], store)
        r.start(tid, "keep this")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        (card,) = components(store, tid)
        assert ask["toolName"] == "offer_save_attachment" and ask["input"] == {"attachment_id": pic["id"], "project": "demo"}
        assert card["component"] == "SaveAttachmentCard" and card["toolCallId"] == ask["browserId"]
        assert card["data"] == {"attachment_id": pic["id"], "project": "demo",
                                "file": {"name": "mock up.png", "mime": "image/png", "size": len(PNG),
                                         "thread_id": tid}}
        assert "RUN_FINISHED" not in types(store, tid)
        assert "base64" not in json.dumps([e for _, e in store.events_after(tid)])

    asyncio.run(go())


def test_another_conversations_file_or_a_bad_project_is_refused():
    async def go():
        store = Store(":memory:")
        other = store.create_thread()["id"]
        theirs = store.add_attachment(other, "secret.pdf", "application/pdf", b"%PDF-1.4 x")
        tid = store.create_thread()["id"]
        mine = store.add_attachment(tid, "a.png", "image/png", PNG)
        for inp in ({"attachment_id": theirs["id"], "project": "demo"},
                    {"attachment_id": "nope", "project": "demo"},
                    {"attachment_id": mine["id"], "project": "../Demo"},
                    {"attachment_id": mine["id"], "project": "demo", "filename": "x.sh"}):
            t = store.create_thread()["id"] if inp["attachment_id"] != mine["id"] else tid
            r, _app, seen = build([("offer_save_attachment", inp)], store)
            r.start(t, "keep it")
            await settle(r, t)
            assert customs(store, t, "browser_tool") == [] and components(store, t) == []
            assert "were not valid" in model_text(seen)
            assert "secret.pdf" not in model_text(seen)

    asyncio.run(go())


def test_results_are_cut_down_to_status_and_reason():
    async def go():
        store = Store(":memory:")
        tid = store.create_thread()["id"]
        pic = store.add_attachment(tid, "a.png", "image/png", PNG)
        r, app, seen = build([("offer_save_attachment", {"attachment_id": pic["id"], "project": "demo"})], store)
        r.start(tid, "keep this")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        body = {"result": {"status": "refused", "reason": "LEAK-reason", "path": "LEAK", "name": "a.png"}}
        async with client(app) as c:
            assert (await c.post(f"/browser-results/{ask['browserId']}", json=body)).status_code == 202
        await settle(r, tid)
        text = model_text(seen)
        assert "refused" in text and "LEAK" not in text
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())
