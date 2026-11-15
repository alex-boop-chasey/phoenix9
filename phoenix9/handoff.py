"""The record of a task handed to the Phoenix agent: tasks/<n>/handoff.json in the run folder.

Phoenix holds the truth about a hand-off here, never the agent. Each hand-off of a task is one item:
{gate, thread, state, why, action, rewrote_checks, started, ended}. States: `working` (the agent has it),
`fixed` (the task passed after it), `gave-up` (the agent handed it back to Alex) and `failed-again` (the
task failed again after the agent's fix). A task is handed over at most LIMIT times per run.
"""
from __future__ import annotations

from pathlib import Path

from phoenix9 import atomic, paths, scrub, state

LIMIT = 2                      # hand-offs per task per run; after that the question waits for Alex
WHY_MAX = 300
STATES = ("working", "fixed", "gave-up", "failed-again")
ACTIONS = ("", "retry", "rewrite-checks")
MARKABLE = ("action", "rewrote_checks", "why", "thread")


def path(run_dir, n: int) -> Path:
    """tasks/<n>/handoff.json in the run folder."""
    return Path(run_dir) / "tasks" / str(int(n)) / "handoff.json"


def _one_line(text, limit: int = WHY_MAX) -> str:
    """Scrubbed text on one line, at most `limit` characters."""
    flat = " ".join(scrub.scrub(str(text or "")).split())
    return flat[:limit]


def load(run_dir, n: int) -> dict:
    """The record of this task ({"count": 0, "items": []} when there is none or it cannot be read)."""
    try:
        data = atomic.read_json(path(run_dir, n))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {"count": 0, "items": []}
    items = [i for i in data["items"] if isinstance(i, dict)]
    count = data.get("count")
    return {"count": count if isinstance(count, int) else len(items), "items": items}


def _save(run_dir, n: int, record: dict) -> None:
    atomic.write_json(path(run_dir, n), record)


def start(run_dir, n: int, gate_id: str, thread_id: str) -> dict:
    """Record a new hand-off of task n (state `working`); returns the new item."""
    record = load(run_dir, n)
    item = {"gate": _one_line(gate_id, 200), "thread": _one_line(thread_id, 200), "state": "working", "why": "",
            "action": "", "rewrote_checks": False, "started": state.now(), "ended": ""}
    record["items"].append(item)
    record["count"] += 1
    _save(run_dir, n, record)
    return item


def current(run_dir, n: int) -> dict | None:
    """The newest hand-off of task n while the agent still has it (state `working`), else None."""
    items = load(run_dir, n)["items"]
    return items[-1] if items and items[-1].get("state") == "working" else None


def finish(run_dir, n: int, end_state: str, why: str = "") -> dict | None:
    """End the current hand-off with this state (fixed, gave-up or failed-again); returns it, or None when none is working."""
    if end_state not in STATES or end_state == "working":
        raise ValueError(f"not an end state: {end_state!r}")
    record = load(run_dir, n)
    if not record["items"] or record["items"][-1].get("state") != "working":
        return None
    item = record["items"][-1]
    item.update(state=end_state, ended=state.now())
    if why:
        item["why"] = _one_line(why)
    _save(run_dir, n, record)
    return item


def mark(run_dir, n: int, **fields) -> dict | None:
    """Change fields (action, rewrote_checks, why, thread) on the current hand-off; returns it, or None when none is working."""
    unknown = set(fields) - set(MARKABLE)
    if unknown:
        raise ValueError(f"cannot mark {sorted(unknown)} on a hand-off")
    if "action" in fields and fields["action"] not in ACTIONS:
        raise ValueError(f"not a hand-off action: {fields['action']!r}")
    record = load(run_dir, n)
    if not record["items"] or record["items"][-1].get("state") != "working":
        return None
    item = record["items"][-1]
    for key, value in fields.items():
        item[key] = bool(value) if key == "rewrote_checks" else value if key == "action" else _one_line(value)
    _save(run_dir, n, record)
    return item


def rewrite_used(run_dir, n: int) -> bool:
    """True when the agent already rewrote this task's checks on a hand-off in this run."""
    return any(i.get("rewrote_checks") for i in load(run_dir, n)["items"])


def all_items() -> list[dict]:
    """Every hand-off item of every run, each with project, run, task and its index; unreadable files are skipped."""
    root = paths.runs()
    if not root.is_dir():
        return []
    found = []
    for proj in sorted(p for p in root.iterdir() if p.is_dir()):
        for run_dir in sorted(d for d in proj.iterdir() if d.is_dir()):
            tasks = run_dir / "tasks"
            if not tasks.is_dir():
                continue
            for f in sorted(tasks.glob("*/handoff.json")):
                if not f.parent.name.isdigit():
                    continue
                for index, item in enumerate(load(run_dir, int(f.parent.name))["items"]):
                    found.append({**item, "project": proj.name, "run": run_dir.name,
                                  "task": int(f.parent.name), "index": index})
    return found
