"""The resolver: which steps run for an on/off map, and where every need comes from (architecture 4.3)."""
import json
import shutil
from pathlib import Path

import pytest

from phoenix9.library import load_library
from phoenix9.resolve import ResolveError, resolve

DATA = Path(__file__).parent / "data" / "library"
SNAPSHOT = Path(__file__).parent / "data" / "explain-check-writer-on.txt"
ALL_ON = {"planner": True, "check-writer": True, "red-check": True, "builder": True,
          "commit": True, "full-suite": True}


@pytest.fixture
def lib():
    return load_library(DATA)


def library_with(tmp_path: Path, folder: str, text: str):
    """The test library plus one extra step folder."""
    root = tmp_path / "lib"
    shutil.copytree(DATA, root)
    (root / "steps" / folder).mkdir()
    (root / "steps" / folder / "step.toml").write_text(text)
    lib = load_library(root)
    assert lib.problems == []
    return lib


# Criterion 4
def test_all_on_every_need_from_latest_earlier_producer(lib):
    plan = resolve(lib, ALL_ON)
    assert plan.groups == {
        "run-start": ["pick-up", "planner"],
        "task": ["check-writer", "red-check", "builder", "commit", "acceptance"],
        "run-finish": ["full-suite"],
    }
    assert plan.off == {}
    assert plan.sources == {
        "pick-up": {"spec": "provided"},
        "planner": {"spec": "provided", "checks": "fallback:spec-done-when"},
        "check-writer": {"task": "provided", "worktree": "provided"},
        "red-check": {"checks": "step:check-writer"},
        "builder": {"task": "provided", "worktree": "provided", "failures": "provided",
                    "plan": "step:planner"},
        "commit": {"diff": "step:builder"},
        "acceptance": {"checks": "step:check-writer", "worktree": "provided"},
        "full-suite": {"worktree": "provided", "exit-codes": "step:acceptance",
                       "commit": "step:commit"},
    }


def test_latest_of_two_earlier_producers_wins(tmp_path):
    lib = library_with(tmp_path, "fixer", 'name = "fixer"\ntitle = "Fixer"\nkind = "ai"\n'
                       'level = "task"\norder = 35\nneeds = ["diff"]\nproduces = ["diff"]\n')
    plan = resolve(lib, {})
    assert plan.sources["fixer"] == {"diff": "step:builder"}       # never itself
    assert plan.sources["commit"] == {"diff": "step:fixer"}
    plan = resolve(lib, {"fixer": False})
    assert plan.sources["commit"] == {"diff": "step:builder"}


def test_library_defaults_used_for_missing_names(lib):
    plan = resolve(lib, {})
    assert plan.groups["run-start"] == ["pick-up"]
    assert plan.groups["task"] == ["builder", "commit", "acceptance"]
    assert plan.off == {"planner": "off by default", "check-writer": "off by default",
                        "red-check": "needs check-writer, which is off"}
    assert plan.sources["builder"]["plan"] == "fallback:spec-as-written"


# Criterion 5
def test_switched_off_producer_gives_fallback(lib):
    plan = resolve(lib, ALL_ON | {"check-writer": False})
    assert plan.sources["acceptance"]["checks"] == "fallback:spec-done-when"
    assert plan.off["check-writer"] == "switched off"
    plan = resolve(lib, ALL_ON | {"planner": False})
    assert plan.sources["builder"]["plan"] == "fallback:spec-as-written"


# Criterion 6
def test_only_producer_of_no_fallback_thing_off_is_error(lib):
    with pytest.raises(ResolveError) as err:
        resolve(lib, {"commit": False})
    message = str(err.value)
    assert err.value.problems == [message]
    assert "Full suite (full-suite) needs commit" in message
    assert "commit has no fallback" in message
    assert "commit (switched off)" in message
    assert "Turn that back on, or switch off full-suite" in message      # full-suite is switchable


def test_task_step_feeds_run_finish(lib):
    plan = resolve(lib, {})
    assert plan.sources["full-suite"]["exit-codes"] == "step:acceptance"
    assert plan.sources["full-suite"]["commit"] == "step:commit"


def test_every_problem_listed_at_once(tmp_path, lib):
    with pytest.raises(ResolveError) as err:
        resolve(lib, {"builder": False, "ghost": True})
    assert len(err.value.problems) == 2
    bigger = library_with(tmp_path, "lint", 'name = "lint"\ntitle = "Lint"\nkind = "script"\n'
                          'level = "task"\norder = 45\nneeds = ["commit"]\n')
    with pytest.raises(ResolveError) as err:
        resolve(bigger, {"commit": False})
    assert [p.split(" needs")[0] for p in err.value.problems] == ["Lint (lint)", "Full suite (full-suite)"]


def test_producer_that_runs_later_is_named(tmp_path):
    lib = library_with(tmp_path, "early", 'name = "early"\ntitle = "Early"\nkind = "script"\n'
                       'level = "task"\norder = 5\nneeds = ["diff"]\n')
    with pytest.raises(ResolveError, match="builder makes it, but runs later"):
        resolve(lib, {})


# Criterion 7
def test_task_need_from_run_start_step(lib):
    plan = resolve(lib, {"planner": True})
    assert plan.sources["builder"]["plan"] == "step:planner"


def test_run_start_need_never_from_task_step(lib):
    plan = resolve(lib, {"planner": True, "check-writer": True})
    assert plan.sources["planner"]["checks"] == "fallback:spec-done-when"
    assert plan.sources["acceptance"]["checks"] == "step:check-writer"


def test_task_provided_thing_not_available_at_run_level(tmp_path):
    lib = library_with(tmp_path, "early-run", 'name = "early-run"\ntitle = "Early run"\n'
                       'kind = "script"\nlevel = "run"\nphase = "start"\norder = 20\nneeds = ["task"]\n')
    with pytest.raises(ResolveError, match=r"Early run \(early-run\) needs task, but Phoenix only "
                                           r"provides task to task-level steps"):
        resolve(lib, {})


# Criterion 8
def test_always_step_cannot_be_switched_off(lib):
    with pytest.raises(ResolveError, match="Builder can't be switched off"):
        resolve(lib, {"builder": False})
    with pytest.raises(ResolveError, match="Acceptance can't be switched off"):
        resolve(lib, {"acceptance": False})
    assert resolve(lib, {"acceptance": True}).is_on("acceptance")


# Criterion 9
def test_only_with_follows_its_partner(lib):
    plan = resolve(lib, {"check-writer": False, "red-check": True})
    assert not plan.is_on("red-check")
    assert plan.off["red-check"] == "needs check-writer, which is off"
    plan = resolve(lib, {"check-writer": True})
    assert plan.is_on("red-check") and "red-check" not in plan.off
    assert plan.groups["task"][:2] == ["check-writer", "red-check"]


# Criterion 10
def test_unknown_name_in_enabled_is_error(lib):
    with pytest.raises(ResolveError, match="no step called 'teleporter'"):
        resolve(lib, {"teleporter": True})


# Criterion 11
def test_inserting_a_step_changes_nothing_else(tmp_path, lib):
    before = resolve(lib, ALL_ON).to_json()
    bigger = library_with(tmp_path, "lint", 'name = "lint"\ntitle = "Lint"\nkind = "script"\n'
                          'level = "task"\norder = 45\nneeds = ["diff", "worktree"]\n')
    after = resolve(bigger, ALL_ON | {"lint": True}).to_json()
    assert after["groups"]["task"] == ["check-writer", "red-check", "builder", "commit", "lint",
                                       "acceptance"]
    after["groups"]["task"].remove("lint")
    assert after["sources"].pop("lint") == {"diff": "step:builder", "worktree": "provided"}
    after["steps"] = [r for r in after["steps"] if r["name"] != "lint"]
    assert after == before


# Criterion 12
def test_explain_snapshot(lib):
    text = resolve(lib, {"check-writer": True}).explain()
    for word in ("Run start:", "Each task:", "Run finish:", "[safety]", "ON ", "off",
                 "needs checks: from check-writer", "needs plan: fallback 'spec-as-written'",
                 "needs spec: provided by Phoenix"):
        assert word in text
    assert text == SNAPSHOT.read_text()


# Criterion 13
def test_to_json_round_trips(lib):
    plan = resolve(lib, {"check-writer": True})
    data = plan.to_json()
    assert json.loads(json.dumps(data)) == data
    assert data["groups"] == plan.groups and data["sources"] == plan.sources
    assert data["off"] == {"planner": "off by default"}
    row = next(r for r in data["steps"] if r["name"] == "red-check")
    assert row == {"name": "red-check", "title": "Red check", "group": "task", "order": 20,
                   "kind": "script", "safety": True, "default": "on", "on": True, "reason": "",
                   "sources": {"checks": "step:check-writer"}}
