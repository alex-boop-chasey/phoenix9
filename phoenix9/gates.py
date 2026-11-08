"""Gates: questions for Alex stored as files, with answers written as separate files."""
import re
from pathlib import Path

from . import atomic, events, paths, runs, state

class NotOpen(ValueError):
    """The question cannot be answered any more: it was closed, its run has ended, or the run moved on."""


class RunHasEnded(ValueError):
    """A gate cannot be opened: the run is already done, failed or stopped."""


KINDS = ("merge", "plan", "human-task", "escalation", "deploy", "step", "budget")
DEFAULT_ACTIONS = ["approve", "back", "skip", "stop"]
BUDGET_ACTIONS = ["raise", "stop"]
ESCALATION_ACTIONS = ["acknowledged", "skip", "stop"]


def _gates_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "gates"


def _next_number(gdir: Path) -> int:
    """One more than the highest gate number already in the folder."""
    numbers = [int(m.group(1)) for p in gdir.glob("*.json")
               if (m := re.fullmatch(r".*\.(\d+)\.json", p.name))]
    return max(numbers, default=0) + 1


def open_gate(run_dir, *, kind: str, title: str, why: str, task: int | None = None,
              step: str | None = None, links=(), actions: list | None = None, flags=(),
              head: str | None = None, task_statuses: dict | None = None) -> dict:
    """Write a new gate file, set the run (and task) to waiting, and emit gate.opened."""
    if kind not in KINDS:
        raise ValueError(f"unknown gate kind {kind!r}; use one of {', '.join(KINDS)}")
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    if st["status"] in ENDED:
        raise RunHasEnded(f"run {st['run_id']} is already {st['status']}; no question is opened")
    gdir = _gates_dir(run_dir)
    gdir.mkdir(parents=True, exist_ok=True)
    if actions is None:
        actions = ESCALATION_ACTIONS if kind == "escalation" else DEFAULT_ACTIONS
    gate = {"id": f"{st['run_id']}.{_next_number(gdir)}", "run": st["run_id"], "project": st["project"],
            "kind": kind, "title": title, "why": why, "task": task, "step": step,
            "links": [dict(x) for x in links], "actions": list(actions), "flags": list(flags),
            "created": state.now(), "answered": False}
    if head is not None:                      # what the question was about (Merge checks it again on approve)
        gate["head"] = head
    if task_statuses is not None:
        gate["task_statuses"] = dict(task_statuses)
    atomic.write_json(gdir / f"{gate['id']}.json", gate)

    ended = []

    def change(s):
        if s["status"] in ENDED:          # it ended a moment ago: never turn it back into waiting
            ended.append(s["status"])
            return
        s["status"] = "waiting"
        if task is not None and str(task) in s["tasks"]:
            s["tasks"][str(task)]["status"] = "waiting"
    state.update(run_dir, change)
    if ended:
        close_questions(run_dir, f"run {ended[0]}")
        raise RunHasEnded(f"run {st['run_id']} is already {ended[0]}; no question is opened")
    events.emit("gate.opened", project=gate["project"], run=gate["run"], task=task, step=step,
                gate=gate["id"], kind=kind, title=title)
    return gate


ENDED = ("done", "failed", "stopped")
TASK_ENDED = ("passed", "failed", "skipped")


def _answer_path(path: Path) -> Path:
    return path.with_name(path.name[:-5] + ".answer.json")


def held_ids(st: dict) -> set:
    """Every gate id the run records it waits on: current.gate, a task's gate or a waiting step line."""
    ids = {(st.get("current") or {}).get("gate")}
    ids |= {t.get("gate") for t in (st.get("tasks") or {}).values() if t.get("status") not in TASK_ENDED}
    ids |= {x.get("gate") for x in st.get("steps") or [] if x.get("status") == "waiting"}
    ids.discard(None)
    ids.discard("")
    return ids


def held(st: dict, gate_id: str) -> bool:
    """True when the run records that it waits on this gate (see held_ids)."""
    return gate_id in held_ids(st)


def _adoptable(st: dict) -> bool:
    """A waiting run that holds no gate (a crash right after a gate file was written): the runner adopts its newest."""
    if st.get("status") != "waiting" or (st.get("current") or {}).get("gate"):
        return False
    return not any(t.get("gate") and t.get("status") == "waiting" for t in (st.get("tasks") or {}).values()) \
        and not any(x.get("gate") and x.get("status") == "waiting" for x in st.get("steps") or [])


def is_open(gate: dict, st: dict | None, answered: bool = False, newest_unanswered: str | None = None) -> bool:
    """THE rule for an open question: no answer file, its run has not ended, and the run waits on it.

    "Waits on it" = current.gate, a task or step line holding it, or (a waiting run holding nothing)
    it is the run's newest unanswered gate, which the runner adopts (runner.adopt_gate)."""
    if answered or gate.get("answered") or not st or st.get("status") in ENDED:
        return False
    if held(st, gate["id"]):
        return True
    return _adoptable(st) and (newest_unanswered is None or newest_unanswered == gate["id"])


def _number(gate: dict) -> int:
    try:
        return int(str(gate["id"]).rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def _run_gates(run_dir: Path) -> list[dict]:
    """Every gate of one run with `state` (open | answered | closed) and, when there is one, its `answer`."""
    st = state.load(run_dir)
    found = []
    for path in sorted(_gates_dir(run_dir).glob("*.json")):
        if path.name.endswith(".answer.json"):
            continue
        gate = atomic.read_json(path)
        if gate:
            found.append((gate, atomic.read_json(_answer_path(path))))
    unanswered = [g for g, a in found if a is None and not g.get("answered")]
    newest = max(unanswered, key=_number)["id"] if unanswered else None
    out = []
    for gate, answer in found:
        if answer is not None:
            gate_state = "closed" if answer.get("action") == "closed" else "answered"
        else:
            gate_state = "open" if is_open(gate, st, False, newest) else "closed"
        item = {**gate, "state": gate_state}
        if answer is not None:
            item["answer"] = answer
        out.append(item)
    return out


def _run_folders(project: str | None) -> list[Path]:
    root = paths.runs(project) if project else paths.runs()
    if not root.is_dir():
        return []
    projects = [root] if project else [p for p in root.iterdir() if p.is_dir()]
    return [d for proj in projects for d in proj.iterdir() if (d / "gates").is_dir() and (d / "state.json").is_file()]


def list_gates(project: str | None = None, open_only: bool = True) -> list[dict]:
    """Gates across all runs (or one project), oldest first: only the open ones (`is_open`), or all with their state."""
    found = []
    for run_dir in _run_folders(project):
        found += [g for g in _run_gates(run_dir) if not open_only or g["state"] == "open"]
    return sorted(found, key=lambda g: (g["created"], g["id"]))


def orphans(run_dir) -> list[dict]:
    """The run's questions that have no answer yet and are not open: nothing waits on them."""
    return [g for g in run_gates(run_dir) if g["state"] == "closed" and "answer" not in g]


def run_gates(run_dir) -> list[dict]:
    """Every gate of one run with its state (open | answered | closed), oldest first."""
    return sorted(_run_gates(Path(run_dir)), key=lambda g: (g["created"], g["id"]))


def _find(gate_id: str) -> Path | None:
    run_id = gate_id.rsplit(".", 1)[0]
    folder = runs.find_run(run_id)
    path = folder / "gates" / f"{gate_id}.json" if folder else None
    return path if path and path.is_file() else None


def _refuse_if_not_open(path: Path, gate: dict) -> None:
    """Raise when the gate cannot take an answer: answered, closed, its run ended, or the run no longer waits on it."""
    gate_id = gate["id"]
    done = atomic.read_json(_answer_path(path))
    if done is not None and done.get("action") == "closed":
        raise NotOpen(f"Question {gate_id} was closed ({done.get('reason') or 'its run ended'}); "
                      "it cannot be answered any more.")
    if gate.get("answered") or done is not None:
        raise ValueError(f"gate {gate_id} is already answered")
    run_dir = path.parent.parent
    st = state.load(run_dir) or {}
    if st.get("status") in ENDED:
        raise NotOpen(f"Run {gate['run']} is already {st['status']}; its question {gate_id} cannot be answered any more.")
    if not any(g["id"] == gate_id and g["state"] == "open" for g in _run_gates(run_dir)):
        raise NotOpen(f"Run {gate['run']} is not waiting on question {gate_id} any more.")


def answer(gate_id: str, action: str, *, note: str = "", who: str = "cli", by: float | None = None) -> dict:
    """Record the answer to an open gate; the runner reads it later and changes the run itself."""
    path = _find(gate_id)
    if path is None:
        raise ValueError(f"no such gate: {gate_id}")
    answer_path = path.with_name(f"{gate_id}.answer.json")
    gate = atomic.read_json(path)
    _refuse_if_not_open(path, gate)
    if action not in gate["actions"]:
        raise ValueError(f"{action!r} is not allowed here; use one of {', '.join(gate['actions'])}")
    if action == "back" and not note.strip():
        raise ValueError("'back' needs a note saying what to change")
    if action == "raise":
        if isinstance(by, bool) or not isinstance(by, (int, float)) or not 0 < by < 1_000_000:
            raise ValueError("'raise' needs the number of dollars to add, more than 0 (by)")
    result = {"action": action, "note": note, "who": who, "at": state.now()}
    if action == "raise":
        result["by"] = by
    atomic.write_json(answer_path, result)
    gate["answered"] = True
    atomic.write_json(path, gate)
    events.emit("gate.answered", project=gate["project"], run=gate["run"], task=gate.get("task"),
                step=gate.get("step"), gate=gate_id, action=action, who=who)
    return result


def close_questions(run_dir, reason: str, who: str = "phoenix", only: str | None = None) -> list[str]:
    """Close every unanswered question of a run that ended (or just `only` this one): answer file {action: closed, reason, who, at}.

    Called by every way a run ends (and by the runner's start-up catch-up); returns the ids it closed."""
    run_dir = Path(run_dir)
    closed = []
    for path in sorted(_gates_dir(run_dir).glob("*.json")):
        if path.name.endswith(".answer.json") or _answer_path(path).exists():
            continue
        gate = atomic.read_json(path)
        if not gate or (only is not None and gate["id"] != only):
            continue
        atomic.write_json(_answer_path(path), {"action": "closed", "reason": reason, "note": "", "who": who,
                                               "at": state.now()})
        gate["answered"] = True
        atomic.write_json(path, gate)
        events.emit("gate.answered", project=gate["project"], run=gate["run"], task=gate.get("task"),
                    step=gate.get("step"), gate=gate["id"], action="closed", reason=reason, who=who)
        closed.append(gate["id"])
    return closed


def poll(run_dir, gate_id: str) -> dict | None:
    """The answer to this gate if it has been written, else None."""
    return atomic.read_json(_gates_dir(run_dir) / f"{gate_id}.answer.json")


# Merge flags that make a merge question Alex's alone: no chat may answer it, whatever the project allows.
FLAG_MARKED_BY_REPAIR = "tasks marked by a repair"
FLAG_REPAIRED = "run was repaired"
FLAG_NO_FULL_SUITE = "no full suite result"
ALEX_ONLY_FLAGS = (FLAG_MARKED_BY_REPAIR, FLAG_REPAIRED, FLAG_NO_FULL_SUITE)
HANDOFF_FLAG = "handed to the Phoenix agent"      # on an escalation gate sent to the agent (failmodes.HANDOFF_FLAG)
FINISHED_TASK = ("passed", "skipped")


def run_repaired(run_dir) -> bool:
    """True when a repair touched this run: a repair snapshot exists (taken before any step of a note runs),
    or a repair.applied event that was not rolled back."""
    run_dir = Path(run_dir)
    base = run_dir / "repairs"
    if base.is_dir() and any(p.is_dir() and p.name.isdigit() for p in base.iterdir()):
        return True
    for e in events.read(run_dir / "events.jsonl"):
        if e.get("type") == "repair.applied" and not (e.get("data") or {}).get("rolled_back"):
            return True
    return False


def _merge_changed_since(gate: dict) -> bool:
    """Live check for a chat answering a merge question: True (refuse) when the run cannot be read, was repaired,
    or has a task that is not passed or skipped; the flags written when the question opened may be stale."""
    run, project = gate.get("run"), gate.get("project")
    if not run or not project:
        return True
    run_dir = paths.runs(project) / run
    st = atomic.read_json(run_dir / "state.json")
    if not isinstance(st, dict):
        return True
    if any(t.get("status") not in FINISHED_TASK for t in (st.get("tasks") or {}).values()):
        return True
    return run_repaired(run_dir)


def may_answer(gate: dict, who: str, project_settings: dict, action: str | None = None) -> bool:
    """Home chat callers (chat:*) may answer only kinds the project lists; everyone else anything.

    A spending-cap (`budget`) question is Alex's alone: chat:* callers never, not even the home chat.
    The home chat (chat:home) may answer only `acknowledged`, and only on an escalation gate that carries the
    flag "handed to the Phoenix agent" (set when a failed task is handed to it).
    A merge question flagged for a repair (or a missing full suite) is Alex's alone: chat:* callers never."""
    if who.startswith("chat:") and gate.get("kind") == "budget":
        return False                      # raising a cap or stopping on cost is Alex's alone, whatever the project allows
    if who.startswith("chat:") and gate.get("kind") == "merge" and (
            any(f in ALEX_ONLY_FLAGS for f in gate.get("flags") or []) or _merge_changed_since(gate)):
        return False
    if who == "chat:home" and gate["kind"] == "escalation" and HANDOFF_FLAG in (gate.get("flags") or []):
        return action == "acknowledged"
    if not who.startswith("chat:"):
        return True
    return gate["kind"] in (project_settings.get("home_chat_may_answer") or [])


def set_flags(run_dir, gate_id: str, flags) -> dict:
    """Replace the flags on a gate Phoenix itself wrote (used when a hand-off to the agent fails); returns the gate."""
    path = _gates_dir(Path(run_dir)) / f"{gate_id}.json"
    gate = atomic.read_json(path)
    gate["flags"] = list(flags)
    atomic.write_json(path, gate)
    return gate


def read(run_dir, gate_id: str) -> dict | None:
    """The gate file of this run, or None."""
    return atomic.read_json(_gates_dir(run_dir) / f"{gate_id}.json")


def current_answer(run_dir) -> dict | None:
    """The answer to the gate the run is waiting on now (state `current.gate`), or None.

    Only this gate counts: answers to older gates of the run never wake it up again.
    """
    st = state.load(Path(run_dir)) or {}
    gate_id = (st.get("current") or {}).get("gate")
    return poll(run_dir, gate_id) if gate_id else None
