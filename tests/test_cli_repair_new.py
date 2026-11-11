"""Tests for the new `phoenix repair` commands: rerun, resume-from, skip, rewrite-checks, max-tries, restart."""
import json

import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, paths, resolve, settings, state
from phoenix9.__main__ import main
from phoenix9.library import load_library
from phoenix9.ops import runs as runs_ops


def run(capsys, *argv):
    """Run one command and return (code, stdout, stderr)."""
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def make(tmp_path):
    """A paused run with two tasks, the first failed."""
    r = make_run(tmp_path, status="paused")
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    failed = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["x"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": failed, "2": state.new_task("Two")}, steps=[]))
    return r


def command_events():
    """The command events written so far."""
    return [e for e in events.read(paths.events()) if e["type"] == "command"]


@pytest.mark.parametrize("argv", [
    ["rerun", "--task", "1"],
    ["resume-from", "--task", "1"],
    ["skip", "--task", "1", "--why", "not needed"],
    ["rewrite-checks", "--task", "1", "--why", "wrong file"],
])
def test_destructive_commands_need_yes(tmp_path, capsys, argv):
    r = make(tmp_path)
    code, _, err = run(capsys, "repair", argv[0], r["run"], *argv[1:])
    assert code == 1 and "--yes" in err
    assert not [e for e in events.read(paths.events()) if e["type"] == "repair.applied"]


def test_skip_plain_and_json(tmp_path, capsys):
    r = make(tmp_path)
    code, out, _ = run(capsys, "repair", "skip", r["run"], "--task", "1", "--why", "not needed", "--yes",
                       "--who", "agent")
    assert code == 0 and "skipped" in out
    assert state.load(r["run_dir"])["tasks"]["1"]["status"] == "skipped"
    assert any(e["data"].get("who") == "agent" for e in command_events())


def test_rerun_json(tmp_path, capsys):
    r = make(tmp_path)
    code, out, _ = run(capsys, "repair", "rerun", r["run"], "--task", "1", "--yes", "--json")
    assert code == 0 and json.loads(out)["ok"] is True


def test_rerun_needs_one_target(tmp_path, capsys):
    r = make(tmp_path)
    code, _, err = run(capsys, "repair", "rerun", r["run"], "--yes")
    assert code != 0 and "task number or a finish step" in err


def test_max_tries(tmp_path, capsys):
    r = make(tmp_path)
    current = runs_ops.detail(r["project"], r["run"]).get("max_tries") or 1
    code, out, _ = run(capsys, "repair", "max-tries", r["run"], "--tries", str(current + 1))
    assert code == 0 and f"{current + 1} tries" in out
    code, _, err = run(capsys, "repair", "max-tries", r["run"], "--tries", "99")
    assert code != 0 and "too many" in err


def test_restart_needs_project(tmp_path, capsys):
    r = make(tmp_path)
    code, _, err = run(capsys, "repair", "restart", r["run"], "--preset", "quick")
    assert code == 1 and "--project" in err


def test_resume_from_and_rewrite_refuse_bad_input(tmp_path, capsys):
    r = make(tmp_path)
    code, _, err = run(capsys, "repair", "skip", r["run"], "--task", "1", "--why", "  ", "--yes")
    assert code != 0 and "reason" in err
