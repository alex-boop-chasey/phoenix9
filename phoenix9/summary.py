"""The run summary: collect the facts from the run folder, then write them as Markdown or as HTML."""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, events, state

TEMPLATE = Path(__file__).parent / "assets" / "summary.html"


def _parse(stamp):
    """An ISO time string as a datetime (None when it is empty or odd)."""
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _duration(start, end) -> str:
    """Plain words for the time between two ISO strings ('' when unknown)."""
    a, b = _parse(start), _parse(end)
    if not a or not b:
        return ""
    seconds = max(int((b - a).total_seconds()), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{hours}h " if hours else "") + (f"{minutes}m " if hours or minutes else "") + f"{secs}s"


def _task_flag(task: dict) -> str:
    """Why a task needs a look: its last failure reason, why it was skipped, or that it is for a human."""
    if task["status"] == "failed":
        return "FAILED: " + (task.get("flagged") or (task.get("failures") or ["it failed"])[-1])
    if task["status"] == "skipped":
        return "SKIPPED: " + (task.get("note") or "no reason given")
    return ""


def _tasks(st: dict, spec: dict) -> list:
    """One entry per task: number, title, status, tries, flag, and whether it is a task for Alex."""
    human = {t.get("number"): bool(t.get("for_you")) for t in spec.get("tasks", [])}
    out = []
    for n, t in sorted(st.get("tasks", {}).items(), key=lambda kv: int(kv[0])):
        out.append({"number": int(n), "title": t.get("title", ""), "status": t["status"], "tries": t.get("tries", 0),
                    "flag": _task_flag(t), "human": human.get(int(n), False)})
    return out


def _escalations(run_dir: Path) -> list:
    """Every answered question about a task: (task, action, who, title), read from the gate answer events."""
    out = []
    for e in events.read(Path(run_dir) / "events.jsonl"):
        if e.get("type") == "gate.answered" and e.get("task") is not None:
            data = e.get("data") or {}
            out.append({"task": e["task"], "action": data.get("action", ""), "who": data.get("who", ""),
                        "gate": data.get("gate", "")})
    return out


def _full_suite(st: dict, run_dir: Path) -> str:
    """One line about the full suite: its step line and, when there is one, final-report.json."""
    line = next((x for x in st.get("steps", []) if x.get("step") == "full-suite"), None)
    if not line or line["status"] in ("pending", "running", "waiting"):
        return "not run"
    if line["status"] == "skipped":
        return "skipped (" + (line.get("note") or "no reason") + ")"
    report = atomic.read_json(Path(run_dir) / "final-report.json") or {}
    detail = (report.get("notes") or [""])[0] or line.get("note", "")
    return ("passed" if line["status"] == "passed" else "FAILED") + (f": {detail.splitlines()[0]}" if detail else "")


def _screenshots(run_dir: Path) -> list:
    """The *.png files already sitting in the attempt out folders, as paths relative to the run folder."""
    run_dir = Path(run_dir)
    return sorted(str(p.relative_to(run_dir)) for p in run_dir.glob("tasks/*/attempt-*/out/**/*.png")
                  if p.is_file() and not p.is_symlink())


def facts(run_dir, screenshots: bool = False) -> dict:
    """Everything the summary shows, as plain values, from state.json, spec.json, the events and progress.md."""
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    spec = atomic.read_json(run_dir / "spec.json") or {}
    frozen = atomic.read_json(run_dir / "settings.json") or {}
    tasks = _tasks(st, spec)
    ends = [e for e in events.read(run_dir / "events.jsonl") if e.get("type") == "run.finished"]
    finished = ends[-1]["ts"] if ends else ""
    usage = st.get("usage") or {}
    progress = run_dir / "progress.md"
    return {
        "title": spec.get("title") or st["run_id"], "project": st["project"], "run_id": st["run_id"],
        "status": st["status"], "preset": str(spec.get("preset") or frozen.get("preset") or "default"),
        "started": st.get("created", ""), "finished": finished,
        "duration": _duration(st.get("created"), finished or state.now()),
        "tasks": tasks,
        "counts": {k: sum(1 for t in tasks if t["status"] == k) for k in ("passed", "failed", "skipped")},
        "escalations": _escalations(run_dir),
        "full_suite": _full_suite(st, run_dir),
        "cost": f"${float(usage.get('cost_usd') or 0):.2f}", "sessions": str(usage.get("sessions", 0)),
        "progress": progress.read_text(errors="replace").splitlines() if progress.exists() else [],
        "screenshots": _screenshots(run_dir) if screenshots else [],
    }


def _task_line(t: dict) -> str:
    """One plain line for a task."""
    tries = t["tries"]
    line = f"Task {t['number']}: {t['title']} - {t['status']}, {tries} {'try' if tries == 1 else 'tries'}"
    return line + (" (for you)" if t["human"] else "") + (f" [{t['flag']}]" if t["flag"] else "")


def _escalation_line(e: dict) -> str:
    """One plain line for an answered question."""
    return f"Task {e['task']}: {e['action']} by {e['who'] or 'someone'}"


def _for_you(f: dict) -> list:
    """The tasks only Alex can do."""
    return [f"Task {t['number']}: {t['title']}" for t in f["tasks"] if t["human"]]


def markdown(f: dict) -> str:
    """The summary as Markdown (summary.md)."""
    c = f["counts"]
    out = [f"# {f['title']}", "", f"- Project: {f['project']}", f"- Run: {f['run_id']}", f"- Status: {f['status']}",
           f"- Preset: {f['preset']}", f"- Started: {f['started'] or 'unknown'}",
           f"- Finished: {f['finished'] or 'not yet'}", f"- Duration: {f['duration'] or 'unknown'}",
           f"- Tasks: {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped",
           f"- Full suite: {f['full_suite']}", f"- Cost: {f['cost']} in {f['sessions']} Claude session(s)",
           "", "## Tasks", ""]
    out += [f"- {_task_line(t)}" for t in f["tasks"]] or ["- (no tasks)"]
    out += ["", "## Things that needed you", ""]
    out += [f"- {_escalation_line(e)}" for e in f["escalations"]] or ["Nothing."]
    out += ["", "## Things only you can do", ""]
    out += [f"- {x}" for x in _for_you(f)] or ["Nothing."]
    if f["screenshots"]:
        out += ["", "## Screenshots", ""] + [f"- [{p}]({p})" for p in f["screenshots"]]
    return "\n".join(out) + "\n"


def _items(lines, empty: str) -> str:
    """HTML list items, each line escaped."""
    return "\n".join(f"<li>{_html.escape(x)}</li>" for x in lines) or f"<li>{_html.escape(empty)}</li>"


def _paragraph_or_list(lines) -> str:
    """An escaped bullet list, or 'Nothing.' when empty."""
    return "<ul>\n" + _items(lines, "") + "\n</ul>" if lines else "<p>Nothing.</p>"


def html(f: dict) -> str:
    """The same summary as plain HTML (summary.html) from assets/summary.html; every value is escaped."""
    e = _html.escape
    shots = ("<ul>\n" + "\n".join(f'<li><a href="{e(p, quote=True)}">{e(p)}</a></li>' for p in f["screenshots"])
             + "\n</ul>") if f["screenshots"] else "<p>None.</p>"
    values = {
        "title": e(f["title"]), "status": e(f["status"]), "project": e(f["project"]), "run_id": e(f["run_id"]),
        "preset": e(f["preset"]), "started": e(f["started"] or "unknown"), "finished": e(f["finished"] or "not yet"),
        "duration": e(f["duration"] or "unknown"), "full_suite": e(f["full_suite"]), "cost": e(f["cost"]),
        "sessions": e(f["sessions"]), "tasks": _items([_task_line(t) for t in f["tasks"]], "(no tasks)"),
        "escalations": _paragraph_or_list([_escalation_line(x) for x in f["escalations"]]),
        "for_you": _paragraph_or_list(_for_you(f)), "screenshots": shots,
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), TEMPLATE.read_text())

