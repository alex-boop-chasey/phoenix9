"""Tests for the spending meter: usage recording, the monthly cap, unchecked prices, month rollover and /spend."""
import asyncio
import json
from datetime import datetime

import httpx
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import config, llm, runs, spend
from agentkit.store import Store

TEST_PRICES = {"input_per_mtok": 1000.0, "output_per_mtok": 2000.0,
               "cache_read_per_mtok": 100.0, "cache_write_per_mtok": 1500.0}
MODEL = "function::test"


def when(month: int, day: int = 10, year: int = 2026) -> float:
    """A local-time timestamp."""
    return datetime(year, month, day, 12).timestamp()


def make(cap=1.0, prices=None, now=None):
    """A store, a config with test-only prices, a clock we control and a meter."""
    cfg = config.Config(model="test", monthly_cap_usd=cap)
    cfg.prices = {"test": TEST_PRICES if prices is None else prices}
    clock = {"now": now or when(11)}
    return Store(":memory:"), cfg, clock


def build(calls, cap=1.0, prices=None, clock_now=None):
    """Runs with a spend-wrapped scripted model."""
    store, cfg, clock = make(cap, prices, clock_now)
    meter = spend.Meter(store, cfg, lambda: clock["now"])

    async def reply(messages, info):
        calls.append(1)
        yield "Hello."

    inner = FunctionModel(stream_function=reply, model_name="test")
    r = runs.Runs(store, llm.build_agent(llm.SpendModel(inner, meter)))
    return store, meter, clock, r


async def run_once(r, store, text="hi"):
    """Run one message to the end and return the event names and the last event."""
    tid = store.create_thread()["id"]
    r.start(tid, text)
    await asyncio.gather(*r.active.values())
    events = [e for _, e in store.events_after(tid)]
    return events


def test_usage_is_recorded_per_call():
    async def go():
        calls = []
        store, meter, _, r = build(calls)
        await run_once(r, store)
        await run_once(r, store)
        rows = store.usage_since(0)
        assert len(rows) == len(calls) == 2
        assert rows[0]["input_tokens"] > 0 and rows[0]["output_tokens"] > 0
        assert rows[0]["model"] == "test"
        want = sum(r["input_tokens"] * 1000 + r["output_tokens"] * 2000 for r in rows) / 1e6
        assert abs(meter.used_usd() - want) < 1e-9

    asyncio.run(go())


def test_cache_tokens_are_kept_apart_and_priced():
    store, cfg, clock = make()
    meter = spend.Meter(store, cfg, lambda: clock["now"])
    meter.record("test", 1000, 500, cache_read_tokens=10000, cache_write_tokens=2000)
    row = store.usage_since(0)[0]
    assert (row["cache_read_tokens"], row["cache_write_tokens"]) == (10000, 2000)
    expected = (1000 * 1000 + 500 * 2000 + 10000 * 100 + 2000 * 1500) / 1e6
    assert abs(meter.used_usd() - expected) < 1e-9


def test_refused_at_the_cap_before_any_model_call():
    async def go():
        calls = []
        store, meter, _, r = build(calls, cap=1.0)
        store.record_usage("test", 1000, 0, at=when(11, 5))  # costs exactly 1.0 = the cap
        events = await run_once(r, store)
        assert calls == []
        assert events[-1]["type"] == "RUN_ERROR"
        assert events[-1]["message"] == (
            "This month's agent allowance has been used up. "
            "Raise it in the agent settings or wait until next month.")
        assert len(store.usage_since(0)) == 1  # nothing new recorded

    asyncio.run(go())


def test_refused_when_prices_are_not_ready():
    async def go():
        calls = []
        unchecked = {k: "CHECK BEFORE USE" for k in TEST_PRICES}
        store, meter, _, r = build(calls, prices=unchecked)
        events = await run_once(r, store)
        assert calls == []
        assert events[-1]["type"] == "RUN_ERROR"
        assert events[-1]["message"] == (
            "The agent's price list hasn't been checked yet, so it won't start. "
            "Fill in the prices in the agent settings file.")

    asyncio.run(go())


def test_new_month_starts_fresh():
    async def go():
        calls = []
        store, meter, clock, r = build(calls, cap=1.0, clock_now=when(10, 28))
        store.record_usage("test", 1000, 0, at=when(10, 20))
        assert meter.report()["state"] == "used_up" and meter.report()["month"] == "2026-10"
        clock["now"] = when(11, 1)
        assert meter.report() == {"month": "2026-11", "used_share": 0.0, "state": "plenty"}
        events = await run_once(r, store)
        assert calls and events[-1]["type"] == "RUN_FINISHED"

    asyncio.run(go())


def test_december_rolls_into_january():
    store, cfg, clock = make(now=when(12, 31))
    meter = spend.Meter(store, cfg, lambda: clock["now"])
    store.record_usage("test", 1000, 0, at=when(12, 30))
    assert meter.report()["month"] == "2026-12" and meter.report()["state"] == "used_up"
    clock["now"] = when(1, 1, 2027)
    assert meter.report()["month"] == "2027-01" and meter.report()["used_share"] == 0.0


def test_states_plenty_low_used_up():
    store, cfg, clock = make(cap=1.0)
    meter = spend.Meter(store, cfg, lambda: clock["now"])
    assert meter.report()["state"] == "plenty"
    store.record_usage("test", 790, 0, at=when(11))
    assert meter.report()["state"] == "plenty"
    store.record_usage("test", 10, 0, at=when(11))  # now 80%
    assert meter.report()["state"] == "low"
    store.record_usage("test", 500, 0, at=when(11))
    report = meter.report()
    assert report["state"] == "used_up" and report["used_share"] == 1.0


def test_spend_route_needs_the_token_and_shows_no_dollars():
    async def go():
        store, cfg, clock = make(cap=95.0)
        meter = spend.Meter(store, cfg, lambda: clock["now"])
        store.record_usage("test", 40, 10, at=when(11))
        denied = lambda req: req.headers.get("authorization") != "Bearer t"
        app = Starlette(routes=[Route("/spend", spend.spend_route(meter, denied), methods=["GET"])])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/spend")).status_code == 401
            resp = await c.get("/spend", headers={"Authorization": "Bearer t"})
        body = resp.json()
        assert set(body) == {"month", "used_share", "state"}
        assert "$" not in resp.text and "usd" not in resp.text.lower() and "95" not in resp.text
        assert 0 <= body["used_share"] <= 1 and body["state"] == "plenty"

    asyncio.run(go())
