"""Tests for the per-run repair lock: one repair at a time per run, other runs are free."""
import time

import pytest

from phoenix9.ops import common, repair as ops
from phoenix9.repair import lock


def test_second_holder_is_refused_and_lock_is_released(tmp_path):
    """A second hold on the same run is Busy; after the first ends the lock is gone."""
    with lock.held(tmp_path):
        with pytest.raises(lock.Busy):
            with lock.held(tmp_path):
                pass
    assert not lock.lock_path(tmp_path).exists()
    with lock.held(tmp_path):
        pass


def test_other_runs_are_not_blocked(tmp_path):
    """Locks of two different runs do not touch each other."""
    with lock.held(tmp_path / "a"), lock.held(tmp_path / "b"):
        pass


def test_lock_released_after_error(tmp_path):
    """An error inside the block still removes the lock file."""
    with pytest.raises(ValueError):
        with lock.held(tmp_path):
            raise ValueError("boom")
    assert not lock.lock_path(tmp_path).exists()


def test_stale_lock_is_taken_over(tmp_path):
    """A lock file older than the stale time is replaced."""
    with lock.held(tmp_path):
        pass
    path = lock.lock_path(tmp_path)
    path.write_text("")
    old = time.time() - lock.STALE_SECONDS - 5
    import os
    os.utime(path, (old, old))
    with lock.held(tmp_path):
        pass


def test_ops_turn_busy_into_conflict(tmp_path):
    """The ops guard answers a plain Conflict with the agreed words."""
    with lock.held(tmp_path):
        with pytest.raises(common.Conflict, match="Another repair on this run is still going"):
            with ops._one_at_a_time(tmp_path):
                pass
