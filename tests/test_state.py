"""Tests for state.json handling."""
import threading

import pytest

from phoenix9 import state


def make(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    from phoenix9 import atomic
    atomic.write_json(d / "state.json", state.new_state("r", "p"))
    return d


def test_update_bumps_updated_and_saves(tmp_path):
    d = make(tmp_path)
    state.update(d, lambda s: s["usage"].update(sessions=3))
    s = state.load(d)
    assert s["usage"]["sessions"] == 3 and s["updated"] >= s["created"]


def test_bad_status_refused_and_not_saved(tmp_path):
    d = make(tmp_path)
    with pytest.raises(ValueError):
        state.set_status(d, "finished")
    with pytest.raises(ValueError):
        state.update(d, lambda s: s.__setitem__("status", "bogus"))
    with pytest.raises(ValueError):
        state.set_task(d, 1, status="weird")
    assert state.load(d)["status"] == "queued" and state.load(d)["tasks"] == {}


def test_set_status_task_and_step_lines(tmp_path):
    d = make(tmp_path)
    state.set_status(d, "running")
    state.set_task(d, 1, title="T", status="running")
    i = state.add_step_line(d, "g", 1, "builder", "running")
    state.set_step_line(d, i, status="passed", note="ok")
    s = state.load(d)
    assert s["status"] == "running" and s["tasks"]["1"]["title"] == "T"
    line = s["steps"][i]
    assert line["status"] == "passed" and line["started"] and line["finished"] and line["note"] == "ok"


def test_concurrent_updates_both_land(tmp_path):
    d = make(tmp_path)

    def work():
        for _ in range(25):
            state.update(d, lambda s: s["usage"].update(sessions=s["usage"]["sessions"] + 1))

    threads = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state.load(d)["usage"]["sessions"] == 50
