"""Refuse repairs asked by the agent or chat that would loosen a safety check."""
from pathlib import Path

from phoenix9 import atomic
from phoenix9.repair import notes, steps, unlock

REFUSAL = "That needs Alex's approval: ask with `phoenix repair request-unlock`; Alex approves it in the dashboard."
NEVER_REFUSAL = ("That would loosen a safety check (a safety step or setting), so I can't do it, even with approval. "
                 "Only Alex can, from the dashboard or the command line.")
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


def needed_unlocks(folder: Path, note: notes.Note, approve_unlock: bool = False) -> list[str] | None:
    """The unlock names (repair/unlock.py) this note needs from the agent or a chat; None when no approval can cover it."""
    needed = ["force"] if note.force else []
    if approve_unlock:
        needed.append("unlock-checks")
    for s in note.steps:
        if s.kind in ALWAYS_REFUSED:
            needed.append(s.kind)
        elif s.kind == "rewrite-checks" and _checks_locked(Path(folder), s.args["n"]):
            needed.append("unlock-checks")
        elif _step_loosens(Path(folder), s):
            return None                   # turning off a safety step or a safety setting: never, even with approval
    return list(dict.fromkeys(needed))


def refusal(folder: Path, note: notes.Note, who: str, approve_unlock: bool = False,
            use: bool = True) -> str | None:
    """The plain refusal for a repair that loosens a safety check when the agent or chat asks, else None.

    A one-time grant Alex approved in the dashboard for exactly this run, asker and these repairs lets it through:
    it is used (and recorded on the run) here, unless `use` is False (a dry run only looks)."""
    if not is_agent(who):
        return None
    needed = needed_unlocks(folder, note, approve_unlock)
    if needed == []:
        return None
    if needed is None:
        return NEVER_REFUSAL
    grant = unlock.use(folder, who, needed) if use else unlock.find(folder, who, needed)
    return None if grant is not None else REFUSAL
