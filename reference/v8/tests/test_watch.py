"""Tests for phoenix/watch.py. start_run, run_plan, finish_run, check_merged and notify are fakes;
the plans folder, run folders and run.json are real."""
import os
import shutil
import time
from pathlib import Path

from phoenix import __main__ as cli
from phoenix import claude, config, runs, watch
from phoenix import run as prun

GOOD = """# Plan: {name}

Type: change
Repo: alex-boop-chasey/{repo}

## About
A small site used to test the watcher.

## Step 1: Home page
Add a home page.

Done when:
- The home page shows the text "Welcome"
"""

BAD = """# Plan: Broken

Type: sideways
Repo: alex-boop-chasey/broken

## Step 1: Home page
Done when:
- looks good
"""


def drop(name, text, age_s=0):
    """Put a plan file in plans/ (age_s seconds old)."""
    folder = config.paths().plans
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(text)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


class Fakes:
    """Fake run pieces that record the order in which runs are started, run and finished."""

    def __init__(self):
        self.events, self.notes = [], []

    def start_run(self, run_id, hands=None, settings=None):
        self.events.append(("start", run_id))
        return "ready"

    def run_plan(self, run_id, tools=None, settings=None):
        others = [r["run_id"] for r in watch.all_runs() if r["status"] == "running" and r["run_id"] != run_id]
        assert others == [], f"another run is running: {others}"
        prun.note_run(run_id, status="running", base_sha="abc")
        self.events.append(("run", run_id))
        prun.note_run(run_id, status="done")
        return "done"

    def finish_run(self, run_id, hands=None, settings=None):
        self.events.append(("finish", run_id))
        prun.note_run(run_id, finished_at=runs.now_iso())
        return "done"

    def check_merged(self, run_id, hands=None):
        self.events.append(("merged?", run_id))
        return "done"

    def notify(self, text):
        self.notes.append(text)

    def watcher(self):
        return watch.Watcher(start_run=self.start_run, run_plan=self.run_plan, finish_run=self.finish_run,
                             check_merged=self.check_merged, notify=self.notify)


SETTINGS = dict(config.DEFAULTS)


def test_a_dropped_plan_becomes_a_queued_run_and_the_file_is_moved():
    src = drop("bakery.md", GOOD.format(name="Bakery", repo="bakery"))
    f = Fakes()
    [run_id] = watch.pick_up_plans(f.watcher(), SETTINGS)
    assert not src.exists()
    moved = runs.run_dir(run_id) / "1-concept" / "plan.md"
    assert moved.read_text() == GOOD.format(name="Bakery", repo="bakery")
    record = runs.load_run(run_id)
    assert record["status"] == "queued"
    assert (record["repo"], record["plan_name"], record["plan_path"]) == \
        ("alex-boop-chasey/bakery", "Bakery", str(moved))
    assert record["plan_sha"] and record["source_name"] == "bakery.md"
    assert watch.pick_up_plans(f.watcher(), SETTINGS) == []     # picked up only once
    assert f.notes == []


def test_a_bad_plan_gets_error_txt_and_a_notification():
    drop("broken.md", BAD)
    f = Fakes()
    assert watch.watch_once(f.watcher(), SETTINGS) is None      # nothing to run
    [record] = watch.all_runs()
    assert record["status"] == "failed" and record["reason"] == "plan rejected: see ERROR.txt"
    error = (runs.run_dir(record["run_id"]) / "ERROR.txt").read_text()
    assert error.startswith("Phoenix did not start the plan 'broken.md' because it has")
    assert "Type" in error and "Fix the plan" in error
    assert len(f.notes) == 1 and "broken.md" in f.notes[0] and "rejected" in f.notes[0]
    assert f.events == []


def test_plans_and_runs_on_different_disks(monkeypatch):
    """On the VPS plans/ and runs/ are separate Docker volumes: a rename between them fails (EXDEV)."""
    real_replace = os.replace
    plans, runs_root = config.paths().plans, config.paths().runs

    def replace(src, dst):
        if Path(src).is_relative_to(plans) != Path(dst).is_relative_to(plans) or \
                Path(src).is_relative_to(runs_root) != Path(dst).is_relative_to(runs_root):
            raise OSError(18, "Invalid cross-device link")
        return real_replace(src, dst)
    monkeypatch.setattr(watch.os, "replace", replace)
    src = drop("bakery.md", GOOD.format(name="Bakery", repo="bakery"))
    bad = drop("broken.md", BAD, age_s=5)
    f = Fakes()
    ids = watch.pick_up_plans(f.watcher(), SETTINGS)
    assert len(ids) == 2 and not src.exists() and not bad.exists()
    assert list((plans / watch.TAKEN).iterdir()) == []
    good = [i for i in ids if runs.load_run(i)["status"] == "queued"]
    assert (runs.run_dir(good[0]) / "1-concept" / "plan.md").read_text() == GOOD.format(name="Bakery", repo="bakery")
    assert len(f.notes) == 1 and "broken.md" in f.notes[0]


def test_a_plan_claimed_before_a_stop_is_finished_next_round():
    taken = config.paths().plans / watch.TAKEN
    taken.mkdir(parents=True)
    (taken / "20261030-0524-abcd--bakery.md").write_text(GOOD.format(name="Bakery", repo="bakery"))
    (taken / "not-a-claim.md").write_text("ignored")
    f = Fakes()
    assert watch.pick_up_plans(f.watcher(), SETTINGS) == ["20261030-0524-abcd"]
    record = runs.load_run("20261030-0524-abcd")
    assert record["status"] == "queued" and record["source_name"] == "bakery.md"
    assert [p.name for p in taken.iterdir()] == ["not-a-claim.md"]


def test_files_in_the_taken_folder_are_not_new_plans():
    taken = config.paths().plans / watch.TAKEN
    taken.mkdir(parents=True)
    (taken / "x.md").write_text("x")
    assert watch.new_plans() == []


def test_two_queued_runs_start_one_at_a_time_oldest_first():
    drop("second.md", GOOD.format(name="Second", repo="second"), age_s=10)
    drop("first.md", GOOD.format(name="First", repo="first"), age_s=20)
    f = Fakes()
    w = f.watcher()
    first = watch.watch_once(w, SETTINGS)
    names = {r["run_id"]: r["plan_name"] for r in watch.all_runs()}
    assert names[first] == "First"
    second = next(i for i in names if i != first)
    assert f.events == [("start", first), ("run", first), ("finish", first)]
    assert runs.load_run(second)["status"] == "queued"           # still waiting its turn
    assert watch.watch_once(w, SETTINGS) == second
    assert f.events[3:] == [("start", second), ("run", second), ("finish", second)]
    assert watch.watch_once(w, SETTINGS) is None


def test_a_running_run_is_resumed_before_a_queued_one_is_started():
    drop("old.md", GOOD.format(name="Old", repo="old"), age_s=20)
    drop("new.md", GOOD.format(name="New", repo="new"), age_s=10)
    f = Fakes()
    ids = watch.pick_up_plans(f.watcher(), SETTINGS)
    by_name = {runs.load_run(i)["plan_name"]: i for i in ids}
    prun.note_run(by_name["New"], status="running", base_sha="abc")   # e.g. Phoenix restarted mid-run
    assert watch.watch_once(f.watcher(), SETTINGS) == by_name["New"]
    assert ("start", by_name["New"]) not in f.events                  # resumed, not started again
    assert f.events[0] == ("run", by_name["New"])
    assert runs.load_run(by_name["Old"])["status"] == "queued"


def test_a_failed_start_does_not_run_the_loop():
    drop("red.md", GOOD.format(name="Red", repo="red"))
    f = Fakes()

    def red_start(run_id, hands=None, settings=None):
        prun.note_run(run_id, status="failed", reason="main is already red: x", finished_at=runs.now_iso())
        return "failed"

    w = f.watcher()
    w.start_run = red_start
    run_id = watch.watch_once(w, SETTINGS)
    assert runs.load_run(run_id)["status"] == "failed"
    assert f.events == []
    assert watch.watch_once(w, SETTINGS) is None


def test_a_loop_that_ended_without_finishing_is_finished_next_round():
    drop("half.md", GOOD.format(name="Half", repo="half"))
    f = Fakes()
    [run_id] = watch.pick_up_plans(f.watcher(), SETTINGS)
    prun.note_run(run_id, status="done", base_sha="abc")             # killed between run_plan and finish_run
    watch.watch_once(f.watcher(), SETTINGS)
    assert f.events == [("finish", run_id)]
    assert runs.load_run(run_id)["finished_at"]


def test_done_runs_with_a_pr_are_checked_for_a_merge():
    drop("pr.md", GOOD.format(name="Pr", repo="pr"))
    f = Fakes()
    [run_id] = watch.pick_up_plans(f.watcher(), SETTINGS)
    prun.note_run(run_id, status="done", base_sha="abc", finished_at="x", pr_url="https://github.com/a/b/pull/1")
    watch.watch_once(f.watcher(), SETTINGS)
    assert f.events == [("merged?", run_id)]


def test_a_crashing_run_is_retried_then_failed_after_three_crashes():
    drop("crash.md", GOOD.format(name="Crash", repo="crash"))
    f = Fakes()
    w = f.watcher()

    def crash(run_id, tools=None, settings=None):
        prun.note_run(run_id, status="running", base_sha="abc")
        raise RuntimeError("docker went away")

    w.run_plan = crash
    run_id = watch.watch_once(w, SETTINGS)
    assert runs.load_run(run_id)["status"] == "running"
    watch.watch_once(w, SETTINGS)
    assert runs.load_run(run_id)["status"] == "running"
    watch.watch_once(w, SETTINGS)
    record = runs.load_run(run_id)
    assert record["status"] == "failed" and "docker went away" in record["reason"]
    assert any("failed" in n and "docker went away" in n for n in f.notes)


def test_limit_wait_longer_than_an_hour_is_notified_once():
    notes, slept = [], []

    def fake_wait(result, probe, now, sleep, **kw):
        for _ in range(4):
            sleep(1800)
        return True

    wrapped = watch.limit_notice("r1", fake_wait, notes.append)
    assert wrapped(claude.Result(kind="rate_limited"), None, None, slept.append, probe_min=30) is True
    assert slept == [1800] * 4
    assert len(notes) == 1 and "more than an hour" in notes[0]
    notes.clear()
    watch.limit_notice("r1", lambda r, p, n, sleep, **kw: sleep(600) or True, notes.append)(
        claude.Result(kind="rate_limited"), None, None, slept.append)
    assert notes == []


def test_watch_once_passes_the_limit_notice_into_the_loop():
    drop("limit.md", GOOD.format(name="Limit", repo="limit"))
    f = Fakes()
    w = f.watcher()
    seen = {}

    def run_plan(run_id, tools=None, settings=None):
        seen["wait"] = tools.wait_for_limit
        tools.wait_for_limit(claude.Result(kind="rate_limited"), None, None, lambda s: None)
        prun.note_run(run_id, status="done", base_sha="abc")
        return "done"

    w.loop_tools.wait_for_limit = lambda r, p, n, sleep, **kw: sleep(7200) or True
    w.run_plan = run_plan
    watch.watch_once(w, SETTINGS)
    assert any("more than an hour" in n for n in f.notes)


def test_cli_has_a_watch_command():
    args = cli.build_parser().parse_args(["watch"])
    assert args.func is cli.cmd_watch


def test_end_to_end_a_dropped_plan_is_built_finished_and_has_a_pr(tmp_path, monkeypatch):
    """The real watcher, step loop, git and run record; only containers, gh and notify are fakes."""
    from test_loop import Fakes as LoopFakes
    from test_run import PLAN as RUN_PLAN, PR_URL, Fakes as RunFakes, make_run, sh

    bare = make_run(tmp_path, monkeypatch)                       # origin with package.json
    runs_dir = config.paths().runs
    for p in runs_dir.iterdir():                                 # only the dropped plan should be a run
        shutil.rmtree(p)
    drop("bakery.md", RUN_PLAN.format(type="change"))
    lf, rf = LoopFakes(passes=(1,)), RunFakes(suite=[0])
    w = watch.Watcher(hands=rf.hands(), loop_tools=lf.tools(), notify=rf.notify)
    run_id = watch.watch_once(w, SETTINGS)
    record = runs.load_run(run_id)
    assert record["status"] == "done" and record["pr_url"] == PR_URL
    assert [e["status"] for e in record["steps"]] == ["passed", "for_you"]
    assert record["full_suite"]["start"] == "green" and record["full_suite"]["end"] == "green"
    assert sh(bare, "rev-parse", f"refs/heads/phoenix/{run_id}").strip() == record["final_commit"]
    summary = (runs.run_dir(run_id) / "summary.md").read_text()
    assert "Step 2: Connect the shop's Stripe account" in summary.partition("## Things only you can do")[2]
    assert rf.notes[-1].startswith(f"Phoenix run {run_id} done: 1 of 2 steps passed")
    rf.pr_state = "MERGED"
    watch.watch_once(w, SETTINGS)
    assert runs.load_run(run_id)["status"] == "merged"
