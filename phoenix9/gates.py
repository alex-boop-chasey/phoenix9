"""Gates: questions for Alex stored as files, with answers written as separate files."""
import re
from pathlib import Path

from . import atomic, events, paths, runs, state

KINDS = ("merge", "plan", "human-task", "escalation", "deploy", "step")
DEFAULT_ACTIONS = ["approve", "back", "skip", "stop"]
ESCALATION_ACTIONS = ["acknowledged", "skip", "stop"]


def _gates_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "gates"


def _next_number(gdir: Path) -> int:
    """One more than the highest gate number already in the folder."""
    numbers = [int(m.group(1)) for p in gdir.glob("*.json")
               if (m := re.fullmatch(r".*\.(\d+)\.json", p.name))]
    return max(numbers, default=0) + 1


def open_gate(run_dir, *, kind: str, title: str, why: str, task: int | None = None,
              step: str | None = None, links=(), actions: list | None = None, flags=()) -> dict:
    """Write a new gate file, set the run (and task) to waiting, and emit gate.opened."""
    if kind not in KINDS:
        raise ValueError(f"unknown gate kind {kind!r}; use one of {', '.join(KINDS)}")
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    gdir = _gates_dir(run_dir)
    gdir.mkdir(parents=True, exist_ok=True)
    if actions is None:
        actions = ESCALATION_ACTIONS if kind == "escalation" else DEFAULT_ACTIONS
    gate = {"id": f"{st['run_id']}.{_next_number(gdir)}", "run": st["run_id"], "project": st["project"],
            "kind": kind, "title": title, "why": why, "task": task, "step": step,
            "links": [dict(x) for x in links], "actions": list(actions), "flags": list(flags),
            "created": state.now(), "answered": False}
    atomic.write_json(gdir / f"{gate['id']}.json", gate)

    def change(s):
        s["status"] = "waiting"
        if task is not None and str(task) in s["tasks"]:
            s["tasks"][str(task)]["status"] = "waiting"
    state.update(run_dir, change)
    events.emit("gate.opened", project=gate["project"], run=gate["run"], task=task, step=step,
                gate=gate["id"], kind=kind, title=title)
    return gate


def _gate_files(project: str | None):
    root = paths.runs(project) if project else paths.runs()
    if not root.is_dir():
        return []
    folders = [root] if project else [p for p in root.iterdir() if p.is_dir()]
    files = []
    for proj in folders:
        files += [p for p in proj.glob("*/gates/*.json") if not p.name.endswith(".answer.json")]
    return files


def list_gates(project: str | None = None, open_only: bool = True) -> list[dict]:
    """Gates across all runs (or one project); open ones have no answer file. Oldest first."""
    found = []
    for path in _gate_files(project):
        gate = atomic.read_json(path)
        if not gate:
            continue
        is_open = not path.with_name(path.name[:-5] + ".answer.json").exists()
        if is_open or not open_only:
            found.append(gate)
    return sorted(found, key=lambda g: (g["created"], g["id"]))


def _find(gate_id: str) -> Path | None:
    run_id = gate_id.rsplit(".", 1)[0]
    folder = runs.find_run(run_id)
    path = folder / "gates" / f"{gate_id}.json" if folder else None
    return path if path and path.is_file() else None


def answer(gate_id: str, action: str, *, note: str = "", who: str = "cli") -> dict:
    """Record the answer to an open gate; the runner reads it later and changes the run itself."""
    path = _find(gate_id)
    if path is None:
        raise ValueError(f"no such gate: {gate_id}")
    answer_path = path.with_name(f"{gate_id}.answer.json")
    gate = atomic.read_json(path)
    if gate.get("answered") or answer_path.exists():
        raise ValueError(f"gate {gate_id} is already answered")
    if action not in gate["actions"]:
        raise ValueError(f"{action!r} is not allowed here; use one of {', '.join(gate['actions'])}")
    if action == "back" and not note.strip():
        raise ValueError("'back' needs a note saying what to change")
    result = {"action": action, "note": note, "who": who, "at": state.now()}
    atomic.write_json(answer_path, result)
    gate["answered"] = True
    atomic.write_json(path, gate)
    events.emit("gate.answered", project=gate["project"], run=gate["run"], task=gate.get("task"),
                step=gate.get("step"), gate=gate_id, action=action, who=who)
    return result


def poll(run_dir, gate_id: str) -> dict | None:
    """The answer to this gate if it has been written, else None."""
    return atomic.read_json(_gates_dir(run_dir) / f"{gate_id}.answer.json")


def may_answer(gate: dict, who: str, project_settings: dict) -> bool:
    """Home chat callers (chat:*) may answer only kinds the project lists; everyone else anything."""
    if not who.startswith("chat:"):
        return True
    return gate["kind"] in (project_settings.get("home_chat_may_answer") or [])
