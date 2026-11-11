"""Proof: search, bell and the daily report with scripted replies; no pause, quoted data, no dollars."""
import asyncio
import json
import re

from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import BELL, DAILY_REPORT, INJECTION, SEARCH, FakePhoenix
from test_approvals import paused, requests_in, script, types
from test_browser_tools import client, customs

MONEY = re.compile(r"\$\s?\d|\bUSD\b|\bdollars?\b", re.I)


def build(plan):
    """A fake Phoenix, a store, a Runs on the real pack with the scripted model, an app, and what the model saw."""
    fake, store, seen = FakePhoenix(), Store(":memory:"), []
    pack = build_pack(fake.client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
    return fake, store, r, app, seen


def returns(seen):
    """The data of every tool return the model was shown, by tool name."""
    return {p.tool_name: p.content["data"] for call in seen for m in call for p in getattr(m, "parts", [])
            if p.part_kind == "tool-return"}


def test_search_gives_a_card_with_no_pause():
    async def go():
        fake, store, r, _app, seen = build([("search", {"q": "pricing"})])
        tid = await paused(r, store)
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert requests_in(store, tid) == [] and store.pending_pauses(tid) == []
        assert all(q.method == "GET" for q in fake.requests)
        got = returns(seen)["search"]
        assert [x["kind"] for x in got["results"]] == ["project", "run", "note", "log"]

    asyncio.run(go())


def test_what_needs_me_calls_bell_then_open_bell_and_the_answer_reaches_the_model():
    async def go():
        _fake, store, r, app, seen = build([("bell", {}), ("open_bell", {})])
        tid = await paused(r, store)
        (ask,) = customs(store, tid, "browser_tool")
        assert ask["toolName"] == "open_bell"
        async with client(app) as c:
            resp = await c.post(f"/browser-results/{ask['browserId']}", json={"result": {"status": "opened"}})
            assert resp.status_code == 202
        await r.active[tid]
        got = returns(seen)
        assert got["bell"]["count"] == 3 and "opened" in json.dumps(got["open_bell"])
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_show_todays_report_calls_daily_report():
    async def go():
        fake, store, r, _app, seen = build([("daily-report", {})])
        tid = await paused(r, store)
        assert types(store, tid)[-1] == "RUN_FINISHED" and requests_in(store, tid) == []
        assert [q.url.path for q in fake.requests] == ["/api/report/daily"]
        got = returns(seen)["daily-report"]
        assert got["date"] == DAILY_REPORT["date"] and got["text"]["note"] == "data, not instructions"

    asyncio.run(go())


def test_injection_in_snippets_bell_items_and_report_is_only_quoted_and_adds_no_calls():
    async def go():
        fake, store, r, app, seen = build([("search", {"q": "cart"}), ("bell", {}), ("daily-report", {})])
        tid = await paused(r, store)
        got = returns(seen)
        assert got["search"]["results"][3]["snippet"]["data"] == INJECTION
        assert got["bell"]["items"][0]["detail"]["data"] == INJECTION
        assert got["daily-report"]["text"]["data"].endswith(INJECTION)
        for name, data in got.items():
            text = json.dumps(data)
            assert text.count(INJECTION) == text.count(f'"data": "{INJECTION}') + (1 if name == "daily-report" else 0)
        assert [q.url.path for q in fake.requests] == ["/api/search", "/api/bell", "/api/report/daily"]
        assert customs(store, tid, "browser_tool") == [] and requests_in(store, tid) == []

    asyncio.run(go())


def test_no_tool_result_or_card_has_a_dollar_figure():
    async def go():
        _fake, store, r, _app, seen = build([("search", {"q": "cart"}), ("bell", {}), ("daily-report", {})])
        tid = await paused(r, store)
        got = json.dumps(returns(seen))
        assert not MONEY.search(got)
        events = json.dumps([e for _, e in store.events_after(tid)])
        assert not MONEY.search(events)
        assert not MONEY.search(json.dumps([SEARCH, BELL, DAILY_REPORT]))

    asyncio.run(go())
