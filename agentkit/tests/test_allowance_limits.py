"""Proof of the allowance limits: 80% is low, 100% refuses, the default cap, no money in /spend, prices must be checked."""
import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import config, spend
from agentkit.store import Store

from test_spend import TEST_PRICES, build, make, run_once, when
import asyncio


def test_79_percent_is_plenty():
    store, cfg, clock = make(cap=100.0)
    meter = spend.Meter(store, cfg, lambda: clock["now"])
    store.record_usage("test", 79000, 0, at=when(11))  # 79 of 100
    assert meter.report()["state"] == "plenty"


def test_80_percent_is_low_and_the_agent_still_answers():
    async def go():
        calls = []
        store, meter, _, r = build(calls, cap=100.0)
        store.record_usage("test", 80000, 0, at=when(11))  # 80 of 100
        assert meter.report()["state"] == "low"
        events = await run_once(r, store)
        assert calls and events[-1]["type"] == "RUN_FINISHED"

    asyncio.run(go())


def test_100_percent_refuses_the_next_call_in_plain_words():
    async def go():
        calls = []
        store, meter, _, r = build(calls, cap=100.0)
        store.record_usage("test", 100000, 0, at=when(11))
        events = await run_once(r, store)
        assert calls == []
        assert events[-1]["type"] == "RUN_ERROR"
        assert events[-1]["message"] == spend.CAP_REACHED
        assert "used up" in events[-1]["message"]

    asyncio.run(go())


def test_default_monthly_cap_is_95():
    assert config.Config().monthly_cap_usd == 95.00


def test_spend_output_has_no_money_figure():
    async def go():
        store, cfg, clock = make(cap=95.0)
        meter = spend.Meter(store, cfg, lambda: clock["now"])
        store.record_usage("test", 40, 10, at=when(11))
        app = Starlette(routes=[Route("/spend", spend.spend_route(meter, lambda r: False), methods=["GET"])])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/spend")
        assert set(resp.json()) == {"month", "used_share", "state"}
        text = resp.text.lower()
        assert "$" not in text and "usd" not in text and "dollar" not in text and "95" not in text

    asyncio.run(go())


def test_unchecked_price_table_still_refuses_the_model():
    async def go():
        calls = []
        unchecked = {k: config.UNCHECKED for k in TEST_PRICES}
        store, meter, _, r = build(calls, prices=unchecked)
        events = await run_once(r, store)
        assert calls == []
        assert events[-1]["message"] == config.PRICES_NOT_READY

    asyncio.run(go())
    assert not config.Config().prices_ready()
