"""Tests that the demo's failed run has events, per-task tries and a session excerpt the read tools can use."""
import json

import pytest

import seed_demo
from phoenix9.ops import repair, runs

PROJECT, RUN = "demo-site", "20261022-140000-blog-section"


@pytest.fixture
def seeded(tmp_path):
    seed_demo.seed(tmp_path / "h", tmp_path / "p")


def test_events_are_readable(seeded):
    got = runs.events(PROJECT, RUN)
    types = [e["type"] for e in got["events"]]
    assert types[0] == "run.queued" and types[-1] == "run.finished"


def test_failed_task_has_one_line_per_try(seeded):
    got = runs.task_tries(PROJECT, RUN)
    assert got["task"] == 2 and [t["attempt"] for t in got["tries"]] == [1, 2, 3]
    assert all(t["status"] == "failed" and t["reason"] for t in got["tries"])


def test_session_excerpt_is_quoted_data(seeded):
    got = runs.session_excerpt(PROJECT, RUN, 2)
    assert got["quoted"] is True and "could not make the checks pass" in got["text"]


def test_diagnosis_lists_every_try(seeded):
    got = repair.diagnose(PROJECT, RUN)
    assert got["task"] == 2 and len(got["tried"]) == 3
    assert got["options"]


def test_failure_line_in_recent_runs(seeded):
    found = {b["run_id"]: b for b in runs.builds(PROJECT)}
    assert found[RUN]["failed_task"] == 2
