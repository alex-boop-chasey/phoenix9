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
