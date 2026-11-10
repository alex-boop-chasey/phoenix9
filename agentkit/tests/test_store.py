"""Tests for the conversation store."""
import time

import pytest

from agentkit.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "sub" / "a.db")
    yield s
    s.close()


def test_numbers_are_gapless_per_thread(store):
    a, b = store.create_thread()["id"], store.create_thread()["id"]
    got = [store.append_event(a, {"n": i}) for i in range(5)]
    assert got == [1, 2, 3, 4, 5]
    assert store.append_event(b, {"x": 1}) == 1
    assert store.append_event(a, {"n": 5}) == 6


def test_read_after_n(store):
    t = store.create_thread()["id"]
    for i in range(4):
        store.append_event(t, {"i": i})
    assert [n for n, _ in store.events_after(t, 2)] == [3, 4]
    assert store.events_after(t, 4) == []
    assert len(store.events_after(t)) == 4


def test_threads_ordered_by_last_used(store):
    a, b, c = (store.create_thread(x)["id"] for x in "abc")
    time.sleep(0.01)
    store.append_event(a, {"hi": 1})
    assert [t["id"] for t in store.list_threads()] == [a, c, b]


def test_pauses(store):
    t = store.create_thread()["id"]
    p = store.create_pause(t, "approval", "set_notify", {"on": True})
    assert store.get_pause(p)["inputs"] == {"on": True}
    assert len(store.pending_pauses(t)) == 1
    assert store.resolve_pause(p, "approved")
    assert not store.resolve_pause(p, "denied")
    assert store.pending_pauses() == []


def test_failed_write_rolls_back(store):
    with pytest.raises(Exception):
        store.append_event("no-such-thread", {})
    t = store.create_thread()["id"]
    assert store.append_event(t, {}) == 1


def test_survives_reopen(tmp_path):
    path = tmp_path / "a.db"
    s = Store(path)
    t = s.create_thread("hello")["id"]
    s.append_event(t, {"k": "v"})
    p = s.create_pause(t, "browser", "go_to", {"url": "x"})
    s.record_usage("m", 1, 2, 3, 4)
    s.close()
    s = Store(path)
    assert s.get_thread(t)["title"] == "hello"
    assert s.events_after(t) == [(1, {"k": "v"})]
    assert s.append_event(t, {}) == 2
    assert s.get_pause(p)["state"] == "pending"
    u = s.usage_since()[0]
    assert (u["input_tokens"], u["output_tokens"], u["cache_read_tokens"], u["cache_write_tokens"]) == (1, 2, 3, 4)
    s.close()
