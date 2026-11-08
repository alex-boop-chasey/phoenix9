"""Tests for the repair steps 'rewrite the checks of task n' and 'rerun finish step': approval, effects and the runner call."""
import importlib.util
from pathlib import Path

import pytest
from helpers import scripted
from helpers.repair_runs import make_run, sh
from helpers.scripted import fail, on

from phoenix9 import atomic, checklock, git, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.repair import apply as apply_mod, steps
from phoenix9.runner import Runner

REPO = Path(__file__).resolve().parents[1]


def ctx_of(r, who="cli", approve=True):
    return steps.Context(r["run_dir"], who=who, approve_unlock=approve)


def note(tmp_path, r, *lines):
    path = tmp_path / "note.md"
    path.write_text(f"# Repair {r['run']}\n\nWhy: test\n\n## Steps\n\n" + "\n".join(f"- {s}" for s in lines) + "\n")
    return path


def task_state(r, n=1):
    return state.load(r["run_dir"])["tasks"][str(n)]


# ------------------------------------------------------------------ rewrite the checks
def checks_run(tmp_path, failures=("SPEC_PROBLEM: the bullet contradicts itself",)):
    """A failed run whose task 1 has a committed, locked check file and passed once steps."""
    r = make_run(tmp_path)
    work = r["work"]
    folder = f"tests/phoenix/{r['run']}/task-1"
    (work / folder).mkdir(parents=True)
    (work / folder / "1-thing.sh").write_text("exit 1\n")
    sh(work, "add", "-A")
    sh(work, "commit", "-q", "-m", "checks")
    checklock.lock(r["run_dir"], 1, work, [f"{folder}/1-thing.sh"])
    atomic.write_json(r["run_dir"] / "settings.json", {"steps": {"check-writer": {"once": True},
                                                                   "red-check": {"once": True}}})

    def change(s):
        s["tasks"] = {"1": {**state.new_task("One"), "status": "failed", "tries": 3, "failures": list(failures),
                            "attempt_base": git.head(work)},
                      "2": {**state.new_task("Two", [1]), "status": "skipped", "note": "depends on task 1, which failed"}}
        s["steps"] = [{"group": "task", "task": 1, "step": name, "status": status, "attempt": 1, "note": ""}
                      for name, status in (("check-writer", "passed"), ("red-check", "passed"), ("builder", "failed"))]
    state.update(r["run_dir"], change)
    r["file"] = work / folder / "1-thing.sh"
    return r


def test_rewrite_checks_removes_checks_and_resets_task(tmp_path):
    r = checks_run(tmp_path)
    out = steps.rewrite_checks(ctx_of(r), 1, "the bullet is impossible")
    assert "removed the locked checks" in out
    assert not r["file"].exists() and not (r["run_dir"] / "tasks/1/checks.lock.json").exists()
    assert sh(r["work"], "status", "--porcelain") == ""
    t = task_state(r)
    assert t["status"] == "pending" and t["tries"] == 0 and t["check_objection"] == "the bullet is impossible"
    assert t["attempt_base"] == git.head(r["work"])
    assert [x["step"] for x in state.load(r["run_dir"])["steps"]] == ["builder"]
    assert task_state(r, 2)["status"] == "pending"


def test_rewrite_checks_allowed_when_a_failure_names_the_locked_file(tmp_path):
    r = checks_run(tmp_path, failures=("1-thing.sh fails whatever the code does",))
    steps.rewrite_checks(ctx_of(r), 1, "bad check")
    assert task_state(r)["status"] == "pending"


def test_rewrite_checks_allowed_by_reviewer_line(tmp_path):
    r = checks_run(tmp_path, failures=("something else",))
    state.update(r["run_dir"], lambda s: s["steps"].append(
        {"group": "task", "task": 1, "step": "reviewer", "status": "failed", "attempt": 1, "note": "SPEC_PROBLEM: no"}))
    steps.rewrite_checks(ctx_of(r), 1, "bad check")
    assert task_state(r)["status"] == "pending"


def test_rewrite_checks_refused_without_a_spec_problem(tmp_path):
    r = checks_run(tmp_path, failures=("the code is wrong",))
    with pytest.raises(steps.StepRefused, match="not the problem"):
        steps.rewrite_checks(ctx_of(r), 1, "why")
    assert r["file"].exists()


def test_rewrite_checks_needs_approval(tmp_path):
    r = checks_run(tmp_path)
    with pytest.raises(steps.StepRefused, match="needs Alex's approval: it unlocks checks"):
        steps.rewrite_checks(ctx_of(r, approve=False), 1, "why")
    with pytest.raises(steps.StepRefused, match="needs Alex's approval"):
        steps.rewrite_checks(ctx_of(r, who="chat:home"), 1, "why")
    assert r["file"].exists() and task_state(r)["status"] == "failed"


def test_rewrite_checks_through_apply_and_undo(tmp_path):
    r = checks_run(tmp_path)
    path = note(tmp_path, r, "rewrite the checks of task 1 because the bullet is impossible", "force")
    refused = apply_mod.apply(path, "agent")
    assert refused["rolled_back"] and r["file"].exists()
    out = apply_mod.apply(path, "cli", approve_unlock=True)
    assert out["ok"] and out["forced"]
    assert not r["file"].exists()


def test_check_writer_prompt_shows_the_objection(tmp_path):
    r = checks_run(tmp_path)
    steps.rewrite_checks(ctx_of(r), 1, "the bullet is impossible")
    spec = importlib.util.spec_from_file_location("check_writer_run", REPO / "steps/check-writer/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from types import SimpleNamespace
    ctx = SimpleNamespace(run=SimpleNamespace(folder=r["run_dir"]), task={"number": 1})
    assert mod._objection(ctx) == "```text\nthe bullet is impossible\n```"
    assert "{{objection}}" in (REPO / "steps/check-writer/prompt.md").read_text()


# ------------------------------------------------------------------ rerun finish step
FINISH = {"merge": dict(level="run", phase="finish", order=30, needs=["spec"], produces=[]),
          "lockfile": dict(level="run", phase="finish", order=40, needs=["spec"], produces=[])}


def finish_run(tmp_path, adapters, monkeypatch, task_status="passed"):
    """A failed run whose only failure is the merge finish step, with a scripted library and a runner on it."""
    scripted.reset()
    lib_dir = scripted.make_library(tmp_path / "lib", {**scripted.STEPS, **FINISH})
    lib = load_library(lib_dir)
    r = make_run(tmp_path)
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())

    def change(s):
        s["tasks"] = {"1": {**state.new_task("One"), "status": task_status}}
        s["steps"] = [{"group": "run-finish", "task": None, "step": "full-suite", "status": "passed", "note": ""},
                      {"group": "run-finish", "task": None, "step": "summary", "status": "passed", "note": ""},
                      {"group": "run-finish", "task": None, "step": "merge", "status": "failed", "note": "conflict"},
                      {"group": "run-finish", "task": None, "step": "lockfile", "status": "skipped", "note": ""}]
        s["error"] = "merge failed"
    state.update(r["run_dir"], change)
    monkeypatch.setattr(steps, "make_runner", lambda: Runner(adapters, lib_dir))
    return r


def lines(r):
    return {x["step"]: x["status"] for x in state.load(r["run_dir"])["steps"] if x["group"] == "run-finish"}


def test_rerun_finish_makes_a_failed_run_done(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch)
    on("merge", None, None, scripted.StepResult("pass"))
    out = steps.rerun_finish(ctx_of(r), "merge")
    st = state.load(r["run_dir"])
    assert st["status"] == "done" and "error" not in st and "now done" in out
    assert lines(r)["merge"] == "passed" and [c["step"] for c in scripted.CALLS].count("merge") == 1


def test_rerun_finish_that_fails_again_keeps_run_failed(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch)
    on("merge", None, None, fail("still a conflict"))
    steps.rerun_finish(ctx_of(r), "merge")
    assert state.load(r["run_dir"])["status"] == "failed" and lines(r)["merge"] == "failed"


def test_rerun_finish_keeps_run_failed_when_a_task_failed(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch, task_status="failed")
    steps.rerun_finish(ctx_of(r), "merge")
    assert lines(r)["merge"] == "passed" and state.load(r["run_dir"])["status"] == "failed"


def test_rerun_skipped_finish_step_adds_a_fresh_line(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch)
    steps.rerun_finish(ctx_of(r), "lockfile")
    assert lines(r)["lockfile"] == "passed" and sum(x["step"] == "lockfile" for x in state.load(r["run_dir"])["steps"]) == 1


def test_rerun_finish_refusals(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch)
    with pytest.raises(steps.StepRefused, match="not a finish step"):
        steps.rerun_finish(ctx_of(r), "builder")
    state.update(r["run_dir"], lambda s: s.__setitem__("status", "stopped"))
    with pytest.raises(steps.StepRefused, match="failed run"):
        steps.rerun_finish(ctx_of(r), "merge")


def test_rerun_finish_through_apply_dry_run_changes_nothing(tmp_path, adapters, monkeypatch):
    r = finish_run(tmp_path, adapters, monkeypatch)
    out = apply_mod.apply(note(tmp_path, r, "rerun finish step merge"), "agent", dry_run=True)
    assert out["dry_run"] and not out["refused"]
    assert state.load(r["run_dir"])["status"] == "failed" and scripted.CALLS == []
    done = apply_mod.apply(note(tmp_path, r, "rerun finish step merge"), "agent")
    assert done["ok"] and state.load(r["run_dir"])["status"] == "done"
