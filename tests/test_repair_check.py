"""Tests for the repair check (state invariants): a healthy run gives nothing, each broken one gives its finding."""
import json
import shutil

from helpers.repair_runs import RUN, make_run, sh

from phoenix9 import __main__ as cli_main, atomic, gates, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.repair import check

G1 = f"{RUN}.1"


def write_consistent_files(run_dir, tasks):
    """settings.json, plan.json and spec.json that agree with each other and with these state tasks."""
    lib = load_library(paths.library())
    values = settings.effective(paths.projects() / "demo", lib).values
    atomic.write_json(run_dir / "settings.json", values)
    enabled = {n: bool(t["on"]) for n, t in values["steps"].items()}
    atomic.write_json(run_dir / "plan.json", json.loads(json.dumps(resolve.resolve(lib, enabled).to_json())))
    atomic.write_json(run_dir / "spec.json", {"title": "Demo", "tasks": [
        {"number": int(n), "title": t["title"], "depends_on": t["depends_on"]} for n, t in tasks.items()]})


def build(tmp_path, status="failed", tasks=None, steps=None, current=None, gate_files=(), attempts=None):
    """A fixture run with exactly this state, these gate files ((n, answer-or-None)) and attempts {task: [results]}."""
    r = make_run(tmp_path, status=status)
    run_dir = r["run_dir"]
    shutil.rmtree(run_dir / "gates")
    shutil.rmtree(run_dir / "tasks")
    st = {"run_id": RUN, "project": r["project"], "status": status, "current": current or {"gate": None},
          "tasks": tasks if tasks is not None else {}, "steps": steps or []}
    atomic.write_json(run_dir / "state.json", st)
    write_consistent_files(run_dir, st["tasks"])
    for n, answer in gate_files:
        gid = f"{RUN}.{n}"
        atomic.write_json(run_dir / "gates" / f"{gid}.json", {"id": gid, "run": RUN, "project": r["project"],
                          "kind": "plan", "title": "t", "task": None, "created": f"2026-11-08T07:0{n}:00",
                          "answered": answer is not None})
        if answer:
            atomic.write_json(run_dir / "gates" / f"{gid}.answer.json", {"action": answer})
    for n, results in (attempts or {}).items():
        for k, res in enumerate(results, 1):
            folder = run_dir / "tasks" / str(n) / f"attempt-{k}"
            folder.mkdir(parents=True)
            if res is not None:
                atomic.write_json(folder / "result.json", {"attempt": k, "status": res})
    return run_dir


def task(status, tries=0, gate=None):
    return {**state.new_task("T"), "status": status, "tries": tries, "gate": gate}


def line(step, status, gate=None):
    return {"group": None, "task": 1, "step": step, "status": status, "gate": gate}


def codes(run_dir):
    return sorted(f.code for f in check.run_checks(run_dir))


def test_healthy_done(tmp_path):
    run_dir = build(tmp_path, "done", {"1": task("passed", 2)}, [line("build", "passed")],
                    attempts={1: ["failed", "passed"]})
    assert check.run_checks(run_dir) == []


def test_healthy_waiting(tmp_path):
    run_dir = build(tmp_path, "waiting", {"1": task("waiting", 1, G1)}, [line("ask", "waiting", G1)],
                    current={"gate": G1}, gate_files=[(1, None)], attempts={1: [None]})
    assert check.run_checks(run_dir) == []


def test_healthy_carrying_on(tmp_path):
    run_dir = build(tmp_path, "waiting", {"1": task("waiting", 1, G1)}, current={"gate": G1},
                    gate_files=[(1, "approve")], attempts={1: [None]})
    assert check.run_checks(run_dir) == []


def test_healthy_stopped_mid_attempt(tmp_path):
    run_dir = build(tmp_path, "stopped", {"1": task("skipped", 3)}, [line("build", "skipped")],
                    attempts={1: ["failed", "failed", None]})
    assert check.run_checks(run_dir) == []


def test_healthy_tries_one_ahead_of_folder(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 2)}, attempts={1: ["failed"]})
    assert check.run_checks(run_dir) == []


def test_bad_status(tmp_path):
    run_dir = build(tmp_path, "running")
    atomic.write_json(run_dir / "state.json", {**state.load(run_dir), "status": "weird"})
    assert codes(run_dir) == ["bad-status"]


def test_bad_task_status(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("nonsense")})
    assert codes(run_dir) == ["bad-status"]


def test_ended_with_task_not_final(tmp_path):
    run_dir = build(tmp_path, "failed", {"1": task("running", 1)}, attempts={1: [None]})
    assert codes(run_dir) == ["task-not-final"]


def test_done_with_failed_task(tmp_path):
    run_dir = build(tmp_path, "done", {"1": task("failed", 1)}, attempts={1: ["failed"]})
    assert codes(run_dir) == ["task-not-final"]


def test_ended_with_step_not_final(tmp_path):
    run_dir = build(tmp_path, "stopped", {"1": task("skipped")}, [line("build", "running")])
    assert codes(run_dir) == ["step-not-final"]


def test_ended_holding_gate(tmp_path):
    run_dir = build(tmp_path, "failed", current={"gate": G1}, gate_files=[(1, "closed")])
    assert codes(run_dir) == ["ended-holds-gate"]


def test_task_waiting_run_running(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("waiting", 1, G1)}, attempts={1: [None]})
    assert codes(run_dir) == ["task-waiting-run-not"]


def test_step_waiting_run_running(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 1)}, [line("ask", "waiting")], attempts={1: [None]})
    assert codes(run_dir) == ["step-waiting-run-not"]


def test_task_running_run_queued(tmp_path):
    run_dir = build(tmp_path, "queued", {"1": task("running", 1)}, attempts={1: [None]})
    assert codes(run_dir) == ["task-running-run-queued"]


def test_step_running_run_queued(tmp_path):
    run_dir = build(tmp_path, "queued", steps=[line("build", "running")])
    assert codes(run_dir) == ["step-running-run-queued"]


def test_attempt_without_result(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 2)}, attempts={1: [None, None]})
    assert codes(run_dir) == ["attempt-no-result"]


def test_attempt_result_for_other_attempt(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 2)}, attempts={1: ["failed", None]})
    atomic.write_json(run_dir / "tasks/1/attempt-1/result.json", {"attempt": 7, "status": "failed"})
    assert codes(run_dir) == ["attempt-wrong-result"]


def test_tries_far_above_folders(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 5)}, attempts={1: ["failed", "failed"]})
    assert codes(run_dir) == ["tries-mismatch"]


def test_gap_in_attempt_folders(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 3)}, attempts={1: ["failed", "failed", None]})
    shutil.rmtree(run_dir / "tasks/1/attempt-2")
    assert codes(run_dir) == ["tries-mismatch"]


def test_folders_with_zero_tries(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("pending", 0)}, attempts={1: [None]})
    assert codes(run_dir) == ["tries-mismatch"]


def test_two_running_lines(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 1)},
                    [line("a", "running"), line("b", "running")], attempts={1: [None]})
    assert codes(run_dir) == ["many-running"]


def test_orphan_question_on_ended_run(tmp_path):
    run_dir = build(tmp_path, "failed", gate_files=[(1, None)])
    assert codes(run_dir) == ["orphan-question"]


def test_orphan_question_on_running_run(tmp_path):
    run_dir = build(tmp_path, "running", gate_files=[(1, None)])
    assert codes(run_dir) == ["orphan-question"]


def test_waiting_without_question(tmp_path):
    run_dir = build(tmp_path, "waiting")
    assert codes(run_dir) == ["waiting-no-question"]


def test_waiting_holding_missing_gate(tmp_path):
    run_dir = build(tmp_path, "waiting", {"1": task("waiting", 1, G1)}, current={"gate": G1}, attempts={1: [None]})
    assert codes(run_dir) == ["waiting-no-question"]


def test_open_gates_helper_agrees(tmp_path):
    run_dir = build(tmp_path, "waiting", current={"gate": G1}, gate_files=[(1, None)])
    assert [g["id"] for g in gates.run_gates(run_dir) if g["state"] == "open"] == [G1]


# ---- worktree, settings, spec, server ---------------------------------------------------------

def healthy(tmp_path, status="failed", tasks=None):
    """A healthy run with a real worktree; returns the make_run paths with run_dir set to the built run."""
    run_dir = build(tmp_path, status, tasks if tasks is not None else {"1": task("passed", 1)},
                    attempts={1: ["passed"]} if tasks is None else None)
    return {"run_dir": run_dir, "work": paths.work("demo", RUN), "code": tmp_path / "code"}


def test_healthy_everything(tmp_path):
    r = healthy(tmp_path)
    assert check.run_checks(r["run_dir"]) == []


def test_worktree_missing(tmp_path):
    r = healthy(tmp_path)
    shutil.rmtree(r["work"])
    assert codes(r["run_dir"]) == ["worktree-missing"]


def test_worktree_not_needed_before_start(tmp_path):
    r = healthy(tmp_path, "queued", {"1": task("pending")})
    shutil.rmtree(r["work"])
    assert codes(r["run_dir"]) == []


def test_worktree_wrong_branch(tmp_path):
    r = healthy(tmp_path)
    sh(r["work"], "checkout", "-q", "-b", "other")
    assert codes(r["run_dir"]) == ["worktree-wrong-branch"]


def test_attempt_base_not_in_worktree(tmp_path):
    r = healthy(tmp_path)
    sh(r["code"], "checkout", "-q", "-b", "side")
    (r["code"] / "side.txt").write_text("x\n")
    sh(r["code"], "add", "-A")
    sh(r["code"], "commit", "-q", "-m", "side")
    stray = sh(r["code"], "rev-parse", "HEAD").strip()
    sh(r["code"], "checkout", "-q", "main")
    st = state.load(r["run_dir"])
    st["tasks"]["1"]["attempt_base"] = stray
    atomic.write_json(r["run_dir"] / "state.json", st)
    assert codes(r["run_dir"]) == ["base-not-in-worktree"]


def test_attempt_base_in_worktree_is_fine(tmp_path):
    r = healthy(tmp_path)
    st = state.load(r["run_dir"])
    st["tasks"]["1"]["attempt_base"] = sh(r["work"], "rev-parse", "HEAD").strip()
    atomic.write_json(r["run_dir"] / "state.json", st)
    assert codes(r["run_dir"]) == []


def test_env_file_in_worktree(tmp_path):
    r = healthy(tmp_path)
    (r["work"] / "sub").mkdir()
    (r["work"] / "sub" / ".env.local").write_text("A=1\n")
    (r["work"] / ".env.example").write_text("A=\n")
    found = check.run_checks(r["run_dir"])
    assert [f.code for f in found] == ["env-file"] and "sub/.env.local" in found[0].text


def test_settings_invalid(tmp_path):
    r = healthy(tmp_path)
    values = atomic.read_json(r["run_dir"] / "settings.json")
    values["no_such_key"] = 1
    atomic.write_json(r["run_dir"] / "settings.json", values)
    assert codes(r["run_dir"]) == ["settings-bad"]


def test_plan_differs_from_settings(tmp_path):
    r = healthy(tmp_path)
    atomic.write_json(r["run_dir"] / "plan.json", {"groups": {}, "steps": []})
    assert codes(r["run_dir"]) == ["plan-differs"]


def test_frozen_plan_may_differ(tmp_path):
    r = healthy(tmp_path)
    atomic.write_json(r["run_dir"] / "plan.json", {"groups": {}, "steps": []})
    atomic.write_json(r["run_dir"] / "repairs" / "frozen.json", {"plan": True})
    assert codes(r["run_dir"]) == []


def test_spec_title_differs(tmp_path):
    r = healthy(tmp_path)
    spec = atomic.read_json(r["run_dir"] / "spec.json")
    spec["tasks"][0]["title"] = "Other"
    atomic.write_json(r["run_dir"] / "spec.json", spec)
    assert codes(r["run_dir"]) == ["spec-task-differs"]


def test_spec_depends_on_differs(tmp_path):
    r = healthy(tmp_path)
    spec = atomic.read_json(r["run_dir"] / "spec.json")
    spec["tasks"][0]["depends_on"] = [2]
    atomic.write_json(r["run_dir"] / "spec.json", spec)
    assert codes(r["run_dir"]) == ["spec-task-differs"]


def test_spec_task_missing(tmp_path):
    r = healthy(tmp_path)
    spec = atomic.read_json(r["run_dir"] / "spec.json")
    spec["tasks"].append({"number": 2, "title": "Two", "depends_on": []})
    atomic.write_json(r["run_dir"] / "spec.json", spec)
    assert codes(r["run_dir"]) == ["spec-task-missing"]


def other_running(tmp_path):
    """A second run of another project whose state says running."""
    other = paths.runs("other") / "20261108-080000-other-run"
    other.mkdir(parents=True)
    atomic.write_json(other / "state.json", {"run_id": other.name, "project": "other", "status": "running", "tasks": {}})


def test_two_runs_running_on_server(tmp_path):
    run_dir = build(tmp_path, "running", {"1": task("running", 1)}, attempts={1: [None]})
    assert codes(run_dir) == []
    other_running(tmp_path)
    assert codes(run_dir) == ["many-runs-running"]


def test_other_running_run_does_not_matter_to_ended_run(tmp_path):
    r = healthy(tmp_path)
    other_running(tmp_path)
    assert codes(r["run_dir"]) == []


# ---- the command ------------------------------------------------------------------------------

def test_cli_no_problems(tmp_path, capsys):
    healthy(tmp_path)
    assert cli_main.main(["repair", "check", RUN]) == 0
    assert "No problems found" in capsys.readouterr().out


def test_cli_numbered_list(tmp_path, capsys):
    r = healthy(tmp_path)
    shutil.rmtree(r["work"])
    atomic.write_json(r["run_dir"] / "plan.json", {"groups": {}, "steps": []})
    assert cli_main.main(["repair", "check", RUN]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("1. ") and out[1].startswith("2. ") and len(out) == 2


def test_cli_json(tmp_path, capsys):
    r = healthy(tmp_path)
    shutil.rmtree(r["work"])
    assert cli_main.main(["repair", "check", RUN, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["problems"][0]["code"] == "worktree-missing"


def test_cli_unknown_run(tmp_path, capsys):
    assert cli_main.main(["repair", "check", "20261108-000000-nope"]) != 0
