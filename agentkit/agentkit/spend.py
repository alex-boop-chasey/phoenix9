"""The spending meter: works out this month's cost from token counts and enforces the monthly cap."""
import time
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import PRICE_KEYS, PRICES_NOT_READY, Config
from .store import Store

CAP_REACHED = (
    "This month's agent allowance has been used up. "
    "Raise it in the agent settings or wait until next month."
)
LOW_FROM = 0.8


class SpendRefused(Exception):
    """Raised before a model call that must not be made; the message is plain English for Alex."""


def month_bounds(now: float) -> tuple[str, float, float]:
    """The calendar month (server local time) holding `now`: its YYYY-MM name, start and end as timestamps."""
    when = datetime.fromtimestamp(now)
    start = datetime(when.year, when.month, 1)
    end = datetime(when.year + (when.month == 12), when.month % 12 + 1, 1)
    return start.strftime("%Y-%m"), start.timestamp(), end.timestamp()


def cost_of(prices: dict, record: dict) -> float:
    """The cost of one usage record, from a price table (per million tokens)."""
    counts = {
        "input_per_mtok": record["input_tokens"],
        "output_per_mtok": record["output_tokens"],
        "cache_read_per_mtok": record["cache_read_tokens"],
        "cache_write_per_mtok": record["cache_write_tokens"],
    }
    return sum(counts[key] * prices[key] for key in PRICE_KEYS) / 1_000_000


class Meter:
    """Records token use and answers how much of this month's allowance is gone."""

    def __init__(self, store: Store, cfg: Config, clock=time.time):
        """Keep the store that holds the usage, the settings (prices and cap) and a clock."""
        self.store, self.cfg, self.clock = store, cfg, clock

    def record(self, model: str, input_tokens: int, output_tokens: int,
               cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> None:
        """Save one model call's tokens; input is the part that was neither read from nor written to the cache."""
        self.store.record_usage(model, input_tokens, output_tokens, cache_read_tokens,
                                cache_write_tokens, at=self.clock())

    def used_usd(self) -> float:
        """This month's total cost; internal only, never shown to anyone."""
        _, start, end = month_bounds(self.clock())
        total = 0.0
        for rec in self.store.usage_since(start):
            prices = self.cfg.prices.get(rec["model"])
            if rec["at"] < end and prices and all(_number(prices.get(k)) for k in PRICE_KEYS):
                total += cost_of(prices, rec)
        return total

    def share(self) -> float:
        """The part of this month's allowance that is used, from 0 to 1."""
        cap = self.cfg.monthly_cap_usd
        return 1.0 if cap <= 0 else min(1.0, self.used_usd() / cap)

    def report(self) -> dict:
        """What GET /spend says: the month, the share used and a state word; never a money figure."""
        share = self.share()
        state = "used_up" if share >= 1 else "low" if share >= LOW_FROM else "plenty"
        return {"month": month_bounds(self.clock())[0], "used_share": round(share, 4), "state": state}

    def check(self) -> None:
        """Raise SpendRefused if the prices aren't ready or this month's allowance is used up."""
        if not self.cfg.prices_ready():
            raise SpendRefused(PRICES_NOT_READY)
        if self.share() >= 1:
            raise SpendRefused(CAP_REACHED)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def spend_route(meter: Meter, denied):
    """Make the GET /spend handler: the month, the share used and a state word."""

    async def spend(request: Request):
        """Report this month's use as a share of the allowance."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse(meter.report())

    return spend
