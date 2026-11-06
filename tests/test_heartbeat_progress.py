"""The heartbeat proves progress, not just a live process: the side thread only refreshes it while the service
loop moved in the last PROGRESS_WINDOW_S seconds, or while a step's container is running (heartbeat.busy)."""
import threading
import time

import pytest

from fakes import fake_adapters
from phoenix9 import heartbeat, watch
from phoenix9.docker import DockerRunner


@pytest.fixture(autouse=True)
def clean_progress():
    heartbeat.reset_progress()
    yield
    heartbeat.reset_progress()


def beat_once(ad):
    """Run the side thread for one tick and return what it wrote (None = nothing)."""
    stop = threading.Event()
    beats = heartbeat.start_ticker(ad.clock, interval_s=0.01, stop=stop)
    time.sleep(0.05)
    stop.set()
    beats.join(1)
    return heartbeat.read()


def test_recent_progress_keeps_the_heartbeat_fresh(tmp_path):
    ad = fake_adapters(tmp_path)
    heartbeat.mark_progress()
    assert beat_once(ad)["at"] == ad.clock.t


def test_a_hung_loop_stops_the_heartbeat(tmp_path):
    ad = fake_adapters(tmp_path)
    heartbeat.mark_progress(at=time.monotonic() - heartbeat.PROGRESS_WINDOW_S - 1)
    assert beat_once(ad) is None
    assert heartbeat.PROGRESS_WINDOW_S == 600


def test_no_progress_ever_means_no_beat(tmp_path):
    assert beat_once(fake_adapters(tmp_path)) is None


def test_a_running_container_counts_as_progress(tmp_path):
    ad = fake_adapters(tmp_path)
    heartbeat.mark_progress(at=time.monotonic() - 3600)
    later = time.monotonic() + heartbeat.PROGRESS_WINDOW_S + 60
    with heartbeat.busy():
        assert heartbeat.making_progress(now=later)          # however long the container runs
        assert beat_once(ad)["at"] == ad.clock.t
    assert heartbeat.making_progress()                       # it ending is progress too...
    assert not heartbeat.making_progress(now=later)          # ...but only for the window


def test_every_loop_round_is_progress(tmp_path):
    from test_watch import FakeRunner
    assert not heartbeat.making_progress()
    watch.watch_once(fake_adapters(tmp_path), FakeRunner())
    assert heartbeat.making_progress()


def test_docker_run_is_busy_while_the_container_runs(tmp_path):
    seen = []
    done = threading.Event()

    def run():
        DockerRunner().run(["sleep", "0.3"], None, None, 10, "phoenix9-test-none")
        done.set()
    t = threading.Thread(target=run)
    t.start()
    for _ in range(100):
        if heartbeat.busy_count():
            seen.append(True)
            break
        time.sleep(0.01)
    t.join(5)
    assert seen and done.is_set() and heartbeat.busy_count() == 0
