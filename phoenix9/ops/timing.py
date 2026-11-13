"""Where a run's time went: clock, waiting on a person, working, per step, tests against AI (read-only)."""
import json
import statistics
import time
from datetime import datetime, timezone

from phoenix9 import events as events_core, runs as runs_core, scrub, state
from phoenix9.ops import common
from phoenix9.ops.runs import FINISHED, _run_folder

TEST_STEPS = ("branch", "acceptance", "verify", "full-suite", "red-check")   # script steps that run tests
SUITE_STEPS = ("branch", "full-suite")                                       # script steps that run the whole suite
ESTIMATE_RUNS = 10          # newest finished runs a typical time is taken from
ESTIMATE_MIN_SAMPLES = 3    # fewer than this in the project: use all projects instead
ESTIMATE_CACHE_S = 300      # how long one project's estimates are kept in memory
_estimate_cache: dict = {}  # project -> (time, answer)
_run_cache: dict = {}       # events.jsonl path -> ((mtime, size), one finished run's step times)


def _when(text) -> datetime | None:
    """A timestamp from an event, or None when it is missing or unreadable."""
    try:
        when = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _merge(spans: list) -> list:
    """Join overlapping (start, end) spans so nothing is counted twice."""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _overlap(a: datetime, b: datetime, spans: list) -> float:
    """Seconds of a..b that fall inside the (merged) spans."""
    return sum(max(0.0, (min(b, y) - max(a, x)).total_seconds()) for x, y in spans)


def _read_events(folder, run_id: str) -> list:
    """The run's events with a readable time, oldest first; unreadable lines are skipped."""
    found = []
    for e in events_core.read(folder / "events.jsonl"):
        when = _when(e.get("ts")) if isinstance(e, dict) else None
        if when and e.get("run") in (None, run_id):
            found.append((when, e))
    return found


def _gate_spans(found: list, end: datetime) -> list:
    """Times a question waited for a person: opened to answered (or to `end` when still open)."""
    opened, spans = {}, []
    for when, e in found:
        data = e.get("data") or {}
        gate = data.get("gate")
        if e.get("type") == "gate.opened":
            opened.setdefault(gate, when)
        elif e.get("type") == "gate.answered" and gate in opened:
            spans.append((opened.pop(gate), when))
    spans += [(w, end) for w in opened.values()]
    return _merge(spans)


def _step_runs(found: list, waits: list) -> list:
    """One (name, seconds) per finished step, with the time a person was being waited for taken out."""
    return [(name, secs) for _, name, secs in _step_runs_by_task(found, waits)]


def _step_runs_by_task(found: list, waits: list) -> list:
    """Like `_step_runs`, but each finished step as (task, name, seconds)."""
    started, runs = {}, []
    for when, e in found:
        key = (e.get("task"), e.get("step"))
        if e.get("type") == "run.step.started":
            started[key] = when
        elif e.get("type") == "run.step.finished" and key in started and e.get("step"):
            begin = started.pop(key)
            secs = max(0.0, (when - begin).total_seconds() - _overlap(begin, when, waits))
            runs.append((e.get("task"), e["step"], secs))
    return runs


def _last_result(path) -> dict | None:
    """The last readable `result` line of an AI session log; bad or half-written lines are skipped."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("type") == "result":
            return item
    return None


def _ai_times(folder) -> dict:
    """Total clock and model seconds over the AI session logs that have a final result line."""
    clock = model = 0.0
    sessions = 0
    for path in sorted((folder / "logs").glob("*.jsonl")):
        item = _last_result(path)
        if not item:
            continue
        a, b = item.get("duration_ms"), item.get("duration_api_ms")
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            clock += a / 1000
            model += b / 1000 if isinstance(b, (int, float)) and not isinstance(b, bool) else 0.0
            sessions += 1
    return {"sessions": sessions, "clock": round(clock, 1), "model": round(model, 1),
            "waiting_on_commands": round(max(0.0, clock - model), 1)}


def _per_step(runs: list, working: float) -> list:
    """Per step name: times run, total, average and share of working time, biggest first."""
    totals = {}
    for name, secs in runs:
        count, total = totals.get(name, (0, 0.0))
        totals[name] = (count + 1, total + secs)
    rows = [{"step": n, "runs": c, "total": round(t, 1), "average": round(t / c, 1),
             "share": round(t / working, 3) if working > 0 else 0.0} for n, (c, t) in totals.items()]
    return sorted(rows, key=lambda r: (-r["total"], r["step"]))


def _tasks(st: dict) -> dict:
    """Task and try counts from state.json; fields older runs lack are simply absent."""
    tasks = {k: t for k, t in (st.get("tasks") or {}).items() if isinstance(t, dict)}
    tries = {k: t["tries"] for k, t in tasks.items() if isinstance(t.get("tries"), int)}
    starts = [v for t in tasks.values() if isinstance(t.get("attempt_starts"), dict)
              for v in t["attempt_starts"].values()]
    out = {"tasks": len(tasks), "tries": tries, "total_tries": sum(tries.values()),
           "already_done": sum(1 for t in tasks.values() if "already done" in str(t.get("note") or ""))}
    if starts:
        out["tries_clean"], out["tries_kept"] = starts.count("clean"), starts.count("kept")
    return out


def timing(project: str, run_id: str) -> dict:
    """Numbers (seconds) for where one run's time went, from its own folder only."""
    common.project_dir(project)
    folder = _run_folder(run_id)
    if folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder) or {}
    found = _read_events(folder, run_id)
    now = datetime.now(timezone.utc)
    running = st.get("status") not in FINISHED
    end = now if running or not found else found[-1][0]
    clock = max(0.0, (end - found[0][0]).total_seconds()) if found else 0.0
    waits = _gate_spans(found, end)
    waiting = min(clock, sum((b - a).total_seconds() for a, b in waits))
    working = max(0.0, clock - waiting)
    runs = _step_runs(found, waits)
    tests = sum(s for n, s in runs if n in TEST_STEPS)
    suite_runs = sum(1 for n, _ in runs if n in SUITE_STEPS)
    skipped = sum(1 for _, e in found if e.get("type") == "suite.skipped")
    return {"project": project, "run_id": run_id, "status": st.get("status"), "in_progress": running,
            "clock": round(clock, 1), "waiting_on_person": round(waiting, 1), "working": round(working, 1),
            "steps": _per_step(runs, working), "test_time": round(tests, 1), "ai": _ai_times(folder),
            **_tasks(st), "suite_runs_made": max(0, suite_runs - skipped), "suite_runs_skipped": skipped}


def _run_sample(folder, run_id: str) -> dict:
    """One finished run's typical times: per step name the average of one run of it, and per task.

    Kept in memory per events file and only read again when that file changes."""
    path = folder / "events.jsonl"
    try:
        info = path.stat()
    except OSError:
        return {"steps": {}, "per_task": None}
    stamp = (info.st_mtime_ns, info.st_size)
    hit = _run_cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    found = _read_events(folder, run_id)
    runs = _step_runs_by_task(found, _gate_spans(found, found[-1][0]) if found else [])
    totals, tasks = {}, {}
    for task, name, secs in runs:
        totals.setdefault(name, []).append(secs)
        if task is not None:
            tasks[task] = tasks.get(task, 0.0) + secs
    sample = {"steps": {n: sum(v) / len(v) for n, v in totals.items()},
              "task_steps": sorted({n for t, n, _ in runs if t is not None}),
              "per_task": sum(tasks.values()) / len(tasks) if tasks else None}
    _run_cache[path] = (stamp, sample)
    return sample


def _samples(rows: list) -> list:
    """The step times of finished runs (newest first), skipping runs whose folder is gone."""
    out = []
    for r in rows:
        if r["status"] not in FINISHED:
            continue
        folder = runs_core.run_dir(r["project"], r["run_id"])
        if folder.is_dir():
            out.append(_run_sample(folder, r["run_id"]))
    return out


def _typical(own: list, every: list) -> dict | None:
    """The median of the newest values from this project, or from all projects when it has too few; None if none."""
    source, values = "project", own[:ESTIMATE_RUNS]
    if len(values) < ESTIMATE_MIN_SAMPLES and len(every) > len(values):
        source, values = "all projects", every[:ESTIMATE_RUNS]
    if not values:
        return None
    return {"seconds": round(statistics.median(values), 1), "samples": len(values), "source": source}


def _work_estimates(project: str) -> dict:
    """Estimates worked out from the run folders (no cache)."""
    own = _samples(runs_core.list_runs(project))
    every = _samples(runs_core.list_runs())
    names = sorted({n for s in every + own for n in s["steps"]})
    steps = {}
    for name in names:
        typical = _typical([s["steps"][name] for s in own if name in s["steps"]],
                           [s["steps"][name] for s in every if name in s["steps"]])
        if typical:
            in_loop = any(name in s["task_steps"] for s in own + every if name in s["steps"])
            steps[name] = {**typical, "per_task": in_loop}
    out = {"project": project, "steps": steps}
    per_task = _typical([s["per_task"] for s in own if s["per_task"] is not None],
                        [s["per_task"] for s in every if s["per_task"] is not None])
    if per_task:
        out["task"] = per_task
    return out


def estimates(project: str) -> dict:
    """Typical seconds for one run of each step and for one task, from past finished builds (kept 5 minutes)."""
    common.project_dir(project)
    now = time.monotonic()
    hit = _estimate_cache.get(project)
    if hit and now - hit[0] < ESTIMATE_CACHE_S:
        return hit[1]
    answer = _work_estimates(project)
    _estimate_cache[project] = (now, answer)
    return answer


def _span(secs: float) -> str:
    """Seconds as plain words: seconds under two minutes, else minutes (and hours when long)."""
    secs = int(round(secs))
    if secs < 120:
        return f"{secs} seconds"
    minutes = round(secs / 60)
    return f"{minutes} minutes" if minutes < 120 else f"{minutes / 60:.1f} hours"


def lines(r: dict) -> list:
    """The numbers as plain-English lines (scrubbed)."""
    out = [f"Run {r['run_id']} ({r['status'] or 'unknown'}"
           + (", still going" if r["in_progress"] else "") + ").",
           f"Total clock time {_span(r['clock'])}: {_span(r['waiting_on_person'])} waiting on a person, "
           f"{_span(r['working'])} working."]
    for s in r["steps"]:
        out.append(f"  {s['step']}: run {s['runs']} time{'s' if s['runs'] != 1 else ''}, {_span(s['total'])} in all, "
                   f"{_span(s['average'])} each, {round(s['share'] * 100)}% of working time.")
    out.append(f"Test steps took {_span(r['test_time'])}.")
    ai = r["ai"]
    if ai["sessions"]:
        out.append(f"AI sessions ({ai['sessions']}): {_span(ai['clock'])} on the clock, {_span(ai['model'])} of model time, "
                   f"{_span(ai['waiting_on_commands'])} waiting on commands.")
    else:
        out.append("No finished AI session logs were found.")
    tries = f"{r['tasks']} tasks, {r['total_tries']} tries in all"
    if "tries_clean" in r:
        tries += f" ({r['tries_clean']} started clean, {r['tries_kept']} kept earlier work)"
    out.append(tries + f"; {r['already_done']} recorded as already done.")
    out.append(f"Whole-suite runs made: {r['suite_runs_made']}; skipped because remembered: {r['suite_runs_skipped']}.")
    return [scrub.scrub(x) for x in out]

