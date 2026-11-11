"""Tests for starting a hotfix: the fixed Quick-plus-Planner overrides, the brief limits and one at a time."""
import json

import pytest

from phoenix9 import events, paths, runs as runs_core, state
from phoenix9.__main__ import main
from phoenix9.ops import runs as runs_ops
from phoenix9.ops.common import OpsError
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)


def test_hotfix_starts_a_quick_run_with_the_planner_on(api):
    make_project("alpha")
    started = runs_ops.start_hotfix("alpha", "Fix the typo on the login page", who="agent")
    folder = runs_core.find_run(started["run_id"])
    assert (folder / "spec.md").read_text().startswith("# Fix the typo on the login page")
    plan = runs_ops.plan("alpha", runs_ops.HOTFIX_OVERRIDES)
    assert plan["errors"] == []
    assert plan["settings"]["preset"] == "quick"
    assert "planner" in plan["groups"]["run-start"]


def test_hotfix_refuses_an_empty_or_long_brief(api):
    make_project("alpha")
    for brief in ("", "   \n", "x" * (runs_ops.HOTFIX_BRIEF_MAX + 1)):
        with pytest.raises(OpsError):
            runs_ops.start_hotfix("alpha", brief)
    assert runs_ops.list_("alpha") == []


def test_second_hotfix_refused_while_one_is_waiting(api):
    make_project("alpha")
    first = runs_ops.start_hotfix("alpha", "First change")
    state.set_status(runs_core.find_run(first["run_id"]), "waiting")
    with pytest.raises(OpsError, match="One hotfix at a time"):
        runs_ops.start_hotfix("alpha", "Second change")


def test_hotfix_allowed_after_the_first_has_ended(api):
    make_project("alpha")
    first = runs_ops.start_hotfix("alpha", "First change")
    state.set_status(runs_core.find_run(first["run_id"]), "done")
    second = runs_ops.start_hotfix("alpha", "Second change")
    assert second["run_id"] != first["run_id"]


def test_a_different_project_is_not_blocked(api):
    make_project("alpha")
    make_project("beta")
    runs_ops.start_hotfix("alpha", "A change")
    assert runs_ops.start_hotfix("beta", "Another change")["project"] == "beta"


def test_cli_hotfix_records_who(api, capsys):
    make_project("alpha")
    assert main(["run", "hotfix", "alpha", "--brief", "Fix it", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"]
    cmds = [e for e in events.read(paths.events()) if e.get("type") == "command"]
    assert any("run hotfix alpha" in json.dumps(e) for e in cmds)
