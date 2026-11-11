"""Refuse repairs asked by the agent or chat that would loosen a safety check."""
from pathlib import Path

from phoenix9 import atomic
from phoenix9.repair import notes, steps

REFUSAL = "That would loosen a safety check, so I can't do it. Alex can do it from the dashboard."
ALWAYS_REFUSED = ("replace-spec", "keep-hand-fix", "reset-worktree")


def is_agent(who: str) -> bool:
    """True when the repair is asked by the agent or a chat session (not Alex's own hands)."""
    return who == "agent" or steps.is_chat(who)


def _is_safety_step(name: str) -> bool:
    """True for a protected step or a step the library marks safety."""
    lib = steps._lib()
    return name in steps.PROTECTED_STEPS or (lib.has_step(name) and bool(lib.step(name).safety))


def _loosens_key(key: str) -> bool:
    """True when a settings key touches the diff rules, a safety setting or a protected or safety step."""
    parts = key.split(".")
    if parts[0] == "diff" or "safety" in key.lower():
        return True
    if parts[0] == "steps" and len(parts) >= 2 and _is_safety_step(parts[1]):
        return True
    return steps._forbidden_key(key) is not None and parts[0] != "steps" and key not in steps.ALLOWED_TOP


def _checks_locked(folder: Path, n: int) -> bool:
    """True when task n has a checks lock with files in it."""
    data = atomic.read_json(folder / "tasks" / str(n) / "checks.lock.json") or {}
    return bool(data.get("files"))


def _step_loosens(folder: Path, step) -> bool:
    """True when this one parsed step loosens a safety check."""
    if step.kind in ALWAYS_REFUSED:
        return True
    if step.kind == "turn-off-step":
        return _is_safety_step(step.args["name"])
    if step.kind == "set-setting":
        return _loosens_key(step.args["key"])
    if step.kind == "rewrite-checks":
        return _checks_locked(folder, step.args["n"])
    return False


def refusal(folder: Path, note: notes.Note, who: str, approve_unlock: bool = False) -> str | None:
    """The plain refusal for a repair that loosens a safety check when the agent or chat asks, else None."""
    if not is_agent(who):
        return None
    if note.force or approve_unlock or any(_step_loosens(Path(folder), s) for s in note.steps):
        return REFUSAL
    return None
