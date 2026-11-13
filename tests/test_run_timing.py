"""Tests for `phoenix run timing`: old-style and new-style run folders, a live run and a corrupt log line."""
import json

from phoenix9 import atomic
from phoenix9.__main__ import main
from phoenix9.ops import controls, timing
from tests.helpers import repair_runs as rr


def _event(ts, type_, task=None, step=None, **data):
    return json.dumps({"ts": f"2026-11-08T{ts}+00:00", "type": type_, "project": rr.PROJECT, "run": rr.RUN,
                       "task": task, "step": step, "data": data})


def _seed(tmp_path, status="done", extra_state=None, events=None, logs=None):
    made = rr.make_run(tmp_path, status=status)
    d = made["run_dir"]
    events = events or [
        _event("10:00:00", "run.started"),
        _event("10:00:00", "run.step.started", 1, "builder"),
        _event("10:10:00", "run.step.finished", 1, "builder", status="passed"),
        _event("10:10:00", "run.step.started", 1, "acceptance"),
        _event("10:20:00", "gate.opened", 1, "acceptance", gate="q-1"),
        _event("10:50:00", "gate.answered", 1, "acceptance", gate="q-1"),
        _event("10:55:00", "run.step.finished", 1, "acceptance", status="passed"),
        _event("10:55:00", "suite.skipped", None, "full-suite", reason="remembered pass"),
        _event("10:55:00", "run.step.started", None, "full-suite"),
        _event("11:00:00", "run.step.finished", None, "full-suite", status="passed"),
        _event("11:00:00", "run.finished"),
    ]
    (d / "events.jsonl").write_text("\n".join(events) + "\n")
    st = {"run_id": rr.RUN, "project": rr.PROJECT, "status": status,
          "tasks": {"1": {"title": "One", "status": "passed", "tries": 2}}}
    st.update(extra_state or {})
    atomic.write_json(d / "state.json", st)
    for name, text in (logs or {}).items():
        (d / "logs").mkdir(exist_ok=True)
        (d / "logs" / name).write_text(text)
    return d


def test_old_style_run(phoenix_env, tmp_path):
    _seed(tmp_path)
    r = timing.timing(rr.PROJECT, rr.RUN)
    assert r["clock"] == 3600 and r["waiting_on_person"] == 1800 and r["working"] == 1800
    steps = {s["step"]: s for s in r["steps"]}
    assert steps["builder"]["total"] == 600 and steps["builder"]["share"] == round(600 / 1800, 3)
    assert steps["acceptance"]["total"] == 900          # 45 minutes minus the 30 spent on the question
    assert r["test_time"] == 900 + 300
    assert r["ai"]["sessions"] == 0 and "tries_clean" not in r
    assert r["total_tries"] == 2 and r["suite_runs_skipped"] == 1 and r["suite_runs_made"] == 0
    assert any("No finished AI session logs" in line for line in timing.lines(r))


def test_new_style_run_with_ai_logs_and_corrupt_line(phoenix_env, tmp_path):
    result = json.dumps({"type": "result", "duration_ms": 600000, "duration_api_ms": 240000})
    _seed(tmp_path, extra_state={"tasks": {
        "1": {"title": "One", "status": "passed", "tries": 2, "attempt_starts": {"1": "clean", "2": "kept"}},
        "2": {"title": "Two", "status": "passed", "tries": 1, "note": "already done: nothing needed changing"}}},
        logs={"1-1-builder.jsonl": '{"type": "assistant"}\n' + result + "\n",
              "1-2-builder.jsonl": "not json at all\n" + '{"type": "result", "duration_ms": 6'})
    r = timing.timing(rr.PROJECT, rr.RUN)
    assert r["ai"] == {"sessions": 1, "clock": 600.0, "model": 240.0, "waiting_on_commands": 360.0}
    assert (r["tasks"], r["tries_clean"], r["tries_kept"], r["already_done"]) == (2, 1, 1, 1)
    text = "\n".join(timing.lines(r))
    assert "10 minutes on the clock" in text and "waiting on commands" in text and "1 started clean" in text


def test_run_in_progress_and_missing_files(phoenix_env, tmp_path):
    d = _seed(tmp_path, status="running", events=[
        _event("10:00:00", "run.started"), _event("10:00:05", "run.step.started", 1, "builder"), "{broken"])
    atomic.write_json(d / "state.json", {"run_id": rr.RUN, "project": rr.PROJECT, "status": "running"})
    r = timing.timing(rr.PROJECT, rr.RUN)
    assert r["in_progress"] and r["clock"] > 0 and r["steps"] == [] and r["tasks"] == 0
    assert "still going" in timing.lines(r)[0]


def test_cli_and_registry(phoenix_env, tmp_path, capsys):
    _seed(tmp_path)
    assert main(["run", "timing", rr.RUN, "--project", rr.PROJECT, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["working"] == 1800
    assert main(["run", "timing", rr.RUN]) == 0
    assert "30 minutes waiting on a person" in capsys.readouterr().out
    c = next(c for c in controls.CONTROLS if c.name == "run-timing")
    assert c.risk == "read" and c.agent == "tool"


def _past_run(project, run_id, status="done", builder_min=10, gate_min=0, planner_min=None, tasks=1):
    """A finished run folder with only state.json and events.jsonl: planner (optional), then builder per task."""
    from phoenix9 import paths
    d = paths.runs(project) / run_id
    d.mkdir(parents=True)
    atomic.write_json(d / "state.json", {"run_id": run_id, "project": project, "status": status,
                                         "created": run_id[:15], "updated": run_id[:15], "tasks": {}})
    lines, t = [], 0

    def ev(minute, type_, task=None, step=None, **data):
        return json.dumps({"ts": f"2026-11-08T{10 + minute // 60:02d}:{minute % 60:02d}:00+00:00", "type": type_,
                           "project": project, "run": run_id, "task": task, "step": step, "data": data})
    if planner_min is not None:
        lines += [ev(t, "run.step.started", None, "planner"), ev(t + planner_min, "run.step.finished", None, "planner")]
        t += planner_min
    for n in range(1, tasks + 1):
        lines.append(ev(t, "run.step.started", n, "builder"))
        if gate_min:
            lines += [ev(t + 1, "gate.opened", n, "builder", gate=f"q-{n}"),
                      ev(t + 1 + gate_min, "gate.answered", n, "builder", gate=f"q-{n}")]
        t += builder_min + gate_min
        lines.append(ev(t, "run.step.finished", n, "builder"))
    (d / "events.jsonl").write_text("\n".join(lines) + "\n")
    return d


def _project(name):
    from phoenix9 import paths
    (paths.projects() / name).mkdir(parents=True, exist_ok=True)


def _fresh():
    timing._estimate_cache.clear()
    timing._run_cache.clear()


def test_estimates_median_of_several_runs(phoenix_env):
    _fresh()
    _project("alpha")
    for i, minutes in enumerate((10, 20, 30, 40, 50)):
        _past_run("alpha", f"20261108-07000{i}-alpha-run", builder_min=minutes, planner_min=2, tasks=2)
    _past_run("alpha", "20261108-080000-alpha-run", status="running", builder_min=999)
    r = timing.estimates("alpha")
    assert r["steps"]["builder"] == {"seconds": 1800.0, "samples": 5, "source": "project", "per_task": True}
    assert r["steps"]["planner"] == {"seconds": 120.0, "samples": 5, "source": "project", "per_task": False}
    assert r["task"] == {"seconds": 1800.0, "samples": 5, "source": "project"}


def test_estimates_use_newest_ten(phoenix_env):
    _fresh()
    _project("alpha")
    for i in range(12):
        _past_run("alpha", f"20261108-0700{i:02d}-alpha-run", builder_min=100 if i < 2 else 5)
    assert timing.estimates("alpha")["steps"]["builder"]["seconds"] == 300 and \
        timing.estimates("alpha")["steps"]["builder"]["samples"] == 10


def test_estimates_fall_back_to_all_projects(phoenix_env):
    _fresh()
    _project("alpha"), _project("beta")
    _past_run("alpha", "20261108-070000-alpha-run", builder_min=1)
    for i in range(3):
        _past_run("beta", f"20261108-07000{i + 1}-beta-run", builder_min=20)
    r = timing.estimates("alpha")
    assert r["steps"]["builder"] == {"seconds": 1200.0, "samples": 4, "source": "all projects", "per_task": True}
    assert timing.estimates("beta")["steps"]["builder"]["source"] == "project"


def test_estimates_empty_history_has_no_entries(phoenix_env):
    _fresh()
    _project("alpha")
    assert timing.estimates("alpha") == {"project": "alpha", "steps": {}}


def test_estimates_leave_out_gate_waiting(phoenix_env):
    _fresh()
    _project("alpha")
    for i in range(3):
        _past_run("alpha", f"20261108-07000{i}-alpha-run", builder_min=10, gate_min=30)
    assert timing.estimates("alpha")["steps"]["builder"]["seconds"] == 600


def test_estimates_cached(phoenix_env, monkeypatch):
    _fresh()
    _project("alpha")
    for i in range(3):
        _past_run("alpha", f"20261108-07000{i}-alpha-run", builder_min=10)
    first = timing.estimates("alpha")
    _past_run("alpha", "20261108-070009-alpha-run", builder_min=500)
    assert timing.estimates("alpha") == first
    real = timing.time.monotonic
    monkeypatch.setattr(timing.time, "monotonic", lambda: real() + timing.ESTIMATE_CACHE_S + 1)
    assert timing.estimates("alpha")["steps"]["builder"]["samples"] == 4


def test_estimates_registry_and_route(phoenix_env):
    from phoenix9.api import server
    c = next(c for c in controls.CONTROLS if c.name == "run-estimates")
    assert c.risk == "read" and c.ops == "timing.estimates"
    import re
    matches = [h for m, p, h in server.ROUTES if m == "GET" and re.fullmatch(p, "/api/runs/alpha/estimates")]
    assert matches[0] is server.get_run_estimates
