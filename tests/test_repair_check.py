"""Tests for the repair check (state invariants): a healthy run gives nothing, each broken one gives its finding."""
import shutil

from helpers.repair_runs import RUN, make_run

from phoenix9 import atomic, gates, state
from phoenix9.repair import check

G1 = f"{RUN}.1"


def build(tmp_path, status="failed", tasks=None, steps=None, current=None, gate_files=(), attempts=None):
    """A fixture run with exactly this state, these gate files ((n, answer-or-None)) and attempts {task: [results]}."""
    r = make_run(tmp_path, status=status)
    run_dir = r["run_dir"]
    shutil.rmtree(run_dir / "gates")
    shutil.rmtree(run_dir / "tasks")
    st = {"run_id": RUN, "project": r["project"], "status": status, "current": current or {"gate": None},
          "tasks": tasks if tasks is not None else {}, "steps": steps or []}
    atomic.write_json(run_dir / "state.json", st)
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
