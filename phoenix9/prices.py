"""Claude list prices, in one place: dollars per million tokens for each model Phoenix knows.

Used only when a session ended without a trustworthy result line (Pause now, a timeout, a crash), so its
cost has to be worked out from the token counts in its stream log. A model not in the table is priced as
the most expensive one, so an unknown model can only over-count, never under-count.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


# Anthropic first-party list prices (cache write = the 5-minute cache, 1.25 x input).
PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(input=10.00, output=50.00, cache_read=0.25, cache_write=12.50),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20, cache_write=5.00),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20, cache_write=2.50),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01, cache_write=0.125),
}

# Short names a step's ai block may use (Claude Code accepts these aliases).
ALIASES = {"fable": "claude-fable-5-1", "opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
           "haiku": "claude-haiku-5-5"}

MOST_EXPENSIVE = max(PRICES.values(), key=lambda p: (p.output, p.input))


def price(model: str | None) -> Price:
    """The price of a model; a date-suffixed id (claude-x-1-20260101) or `[1m]` suffix is matched by its start.
    Unknown or empty models get the most expensive known price."""
    name = str(model or "").strip().lower().split("[", 1)[0]
    name = ALIASES.get(name, name)
    if name in PRICES:
        return PRICES[name]
    match = max((k for k in PRICES if name.startswith(k + "-")), key=len, default=None)
    return PRICES[match] if match else MOST_EXPENSIVE


def cost(model: str | None, usage: dict) -> float:
    """Dollars for one message's `usage` block (input, output, cache read and cache write tokens)."""
    p = price(model)

    def n(key: str) -> float:
        v = usage.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0.0
    return (n("input_tokens") * p.input + n("output_tokens") * p.output
            + n("cache_read_input_tokens") * p.cache_read
            + n("cache_creation_input_tokens") * p.cache_write) / 1_000_000
