"""Tests for reading the agent allowance: each state, unreachable service, and no money words."""
import json

import pytest

from phoenix9 import allowance
from tests.fakes import fake_adapters


def ask(tmp_path, body=None, down=False, status=200):
    """Run allowance.read against a fake agent service."""
    adapters = fake_adapters(tmp_path)
    fake = adapters.agentnext
    fake.down, fake.status = down, status
    if body is not None:
        fake.chunks = [body if isinstance(body, bytes) else json.dumps(body).encode()]
    result = allowance.read(adapters)
    assert fake.calls[0]["url"].endswith("/spend")
    return result


def test_plenty(tmp_path):
    got = ask(tmp_path, {"month": "2026-11", "used_share": 0.1, "state": "plenty"})
    assert got == {"state": "plenty", "used_share": 0.1, "words": "plenty left this month"}


def test_low(tmp_path):
    got = ask(tmp_path, {"month": "2026-11", "used_share": 0.8, "state": "low"})
    assert got["state"] == "low"
    assert got["words"] == "getting low: about 80% of this month's allowance is used"


def test_used_up(tmp_path):
    got = ask(tmp_path, {"month": "2026-11", "used_share": 1.0, "state": "used_up"})
    assert got["state"] == "used_up" and "paused until next month" in got["words"]


@pytest.mark.parametrize("kwargs", [
    {"down": True},
    {"status": 500, "body": {"error": "x"}},
    {"body": b"not json"},
    {"body": {"state": "weird", "used_share": 0.5}},
    {"body": {"state": "low"}},
])
def test_unreachable_or_odd_is_unknown(tmp_path, kwargs):
    got = ask(tmp_path, **kwargs)
    assert got["state"] == "unknown" and got["used_share"] is None


def test_words_never_mention_money(tmp_path):
    for state, share in (("plenty", 0.1), ("low", 0.85), ("used_up", 1.0), ("unknown", 0)):
        text = allowance.words_for(state, share).lower()
        assert "$" not in text and "usd" not in text and "dollar" not in text
