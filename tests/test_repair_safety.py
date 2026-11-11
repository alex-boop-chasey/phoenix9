"""Tests that the agent and chat cannot ask for a repair that loosens a safety check."""
import hashlib
from pathlib import Path

import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.ops import common, repair as ops
from phoenix9.repair import notes, safety


def make(tmp_path):
    """A failed run with one failed task whose checks are locked, and the real library's settings and plan."""
    r = make_run(tmp_path)
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    task = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["SPEC_PROBLEM: bad checks"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": task}, steps=[]))
    atomic.write_json(r["run_dir"] / "tasks" / "1" / "checks.lock.json", {"dir": "tests", "files": {"tests/a.py": "x"}})
    return r


def snap(folder: Path) -> dict:
    """Every file under the folder with its hash."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def text(r, *lines):
    return f"# Repair {r['run']}\n\nWhy: test\n\n## Steps\n\n" + "\n".join(f"- {s}" for s in lines) + "\n"


LOOSENING = [
    ["force"],
    ["rewrite the checks of task 1 because the checks are wrong"],
    ["turn off step diff-rules for this run"],
    ["turn off step secret-scan for this run"],
    ["set diff.deny_extra=[\"x\"] for this run"],
    ["set steps.diff-rules.on=false for this run"],
    ["set safety_files=[\"x\"] for this run"],
    ["replace the spec with notes/other.md"],
    ['keep my hand fix with message "fix"'],
    ["reset the worktree to abcd1234"],
]


@pytest.mark.parametrize("who", ["agent", "chat:home"])
@pytest.mark.parametrize("lines", LOOSENING)
def test_loosening_text_refused_and_run_unchanged(tmp_path, who, lines):
    r = make(tmp_path)
    before = snap(r["run_dir"])
    with pytest.raises(common.Conflict, match="loosen a safety check"):
        ops.apply_text(r["run"], text(r, *lines), who=who)
    assert snap(r["run_dir"]) == before


def test_loosening_note_file_refused_and_unchanged(tmp_path):
    r = make(tmp_path)
    path = tmp_path / "n.md"
    path.write_text(text(r, "retry task 1", "replace the spec with notes/other.md"))
    before = snap(r["run_dir"])
    with pytest.raises(common.Conflict, match="Alex can do it from the dashboard"):
        ops.apply(str(path), who="agent")
    assert snap(r["run_dir"]) == before


def test_approve_unlock_refused_for_agent(tmp_path):
    r = make(tmp_path)
    before = snap(r["run_dir"])
    with pytest.raises(common.Conflict):
        ops.apply_text(r["run"], text(r, "retry task 1"), who="agent", approve_unlock=True)
    assert snap(r["run_dir"]) == before


def test_harmless_repairs_pass_and_alex_is_not_limited(tmp_path):
    r = make(tmp_path)
    for lines in (["retry task 1"], ["set max_tries=5 for this run"], ["resume"],
                  ["mark task 1 skipped because not needed"]):
        note = notes.parse(text(r, *lines))
        assert safety.refusal(r["run_dir"], note, "agent") is None
    for lines in LOOSENING:
        assert safety.refusal(r["run_dir"], notes.parse(text(r, *lines)), "cli") is None


def test_rewrite_checks_allowed_when_not_locked(tmp_path):
    r = make(tmp_path)
    (r["run_dir"] / "tasks" / "1" / "checks.lock.json").unlink()
    note = notes.parse(text(r, "rewrite the checks of task 1 because wrong"))
    assert safety.refusal(r["run_dir"], note, "agent") is None
