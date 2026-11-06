"""The run summary: collect the facts from the run folder, then write them as Markdown or as HTML."""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, events, scrub, settings, state

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
    return friendly_seconds(max(int((b - a).total_seconds()), 0))


def friendly_seconds(seconds: int) -> str:
    """Seconds in friendly units: '45s', '38 min', '2 h 10 min', '5 days'."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours >= 24:
        days = hours // 24
        return f"{days} day{'' if days == 1 else 's'}"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


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
                        "gate": data.get("gate", ""), "reason": data.get("reason", "")})
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


def _waiting(run_dir: Path) -> list:
    """Titles of services this run built without their keys."""
    return [e["title"] for e in atomic.read_json(Path(run_dir) / "deferred-services.json") or []]


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
        "tasks": tasks, "waiting_for_keys": _waiting(run_dir),
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
    """One plain line for an answered (or closed) question."""
    if e["action"] == "closed":
        return f"Task {e['task']}: closed: {e.get('reason') or 'its run ended'}"
    return f"Task {e['task']}: {e['action']} by {e['who'] or 'someone'}"


def _for_you(f: dict) -> list:
    """The tasks only Alex can do."""
    return [f"Task {t['number']}: {t['title']}" for t in f["tasks"] if t["human"]]


FINAL_STATUSES = ("done", "failed", "stopped")


def _status_text(f: dict) -> str:
    """The status in plain words; a run that is not over yet reads 'finishing', never a bare 'running'."""
    if f["status"] in FINAL_STATUSES:
        return f["status"]
    return "finishing (the last steps were still running when this was written)"


def markdown(f: dict) -> str:
    """The summary as Markdown (summary.md)."""
    c = f["counts"]
    out = [f"# {f['title']}", "", f"- Project: {f['project']}", f"- Run: {f['run_id']}", f"- Status: {_status_text(f)}",
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
    if f.get("waiting_for_keys"):
        out += ["", "## Waiting for keys", "", f"Waiting for keys: {', '.join(f['waiting_for_keys'])}"]
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
        "title": e(f["title"]), "status": e(_status_text(f)), "project": e(f["project"]), "run_id": e(f["run_id"]),
        "preset": e(f["preset"]), "started": e(f["started"] or "unknown"), "finished": e(f["finished"] or "not yet"),
        "duration": e(f["duration"] or "unknown"), "full_suite": e(f["full_suite"]), "cost": e(f["cost"]),
        "sessions": e(f["sessions"]), "tasks": _items([_task_line(t) for t in f["tasks"]], "(no tasks)"),
        "escalations": _paragraph_or_list([_escalation_line(x) for x in f["escalations"]]),
        "for_you": _paragraph_or_list(_for_you(f)), "screenshots": shots,
        "waiting": (f"<h2>Waiting for keys</h2>\n<p>Waiting for keys: {e(', '.join(f['waiting_for_keys']))}</p>\n"
                    if f.get("waiting_for_keys") else ""),
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), TEMPLATE.read_text())



def refresh(run_dir, lib_root=None) -> None:
    """Rewrite summary.md and summary.html from fresh facts, only when the run already has a summary.md.
    A failure is appended (scrubbed) to logs/summary.log and never raised."""
    run_dir = Path(run_dir)
    if not (run_dir / "summary.md").exists():
        return
    try:
        name = (atomic.read_json(run_dir / "settings.json") or {}).get("profile") or ""
        profile = settings.load_profile(lib_root, name) if name and lib_root else {}
        shots = bool(profile.get("screenshots"))
        f = facts(run_dir, screenshots=shots)
        atomic.write_text(run_dir / "summary.md", markdown(f))
        atomic.write_text(run_dir / "summary.html", html(f))
    except Exception as err:  # the summary is a courtesy; it must never fail the run
        try:
            log = run_dir / "logs" / "summary.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as fh:
                fh.write(f"could not refresh the summary: {scrub.scrub(str(err))}\n")
        except OSError:
            pass
