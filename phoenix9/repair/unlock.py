"""Alex-approved repair unlocks: the agent or a chat asks, Alex allows it once in the dashboard, one repair uses it."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phoenix9 import atomic, events, gates, scrub, state

KIND = "repair-unlock"
GRANT_MINUTES = 30
# What may be unlocked, with the plain words Alex reads. Anything else stays refused for the agent and chats.
UNLOCKS = {
    "replace-spec": "replace the spec",
    "keep-hand-fix": "keep a hand fix",
    "reset-worktree": "reset the worktree",
    "force": "force a repair past its check",
    "unlock-checks": "unlock locked checks",
    "stop": "stop the run",
    "discard": "discard the run's work",
}
WHY_MAX = 300


class UnlockError(ValueError):
    """A request cannot be made; the message says why in plain words."""


def grants_path(run_dir) -> Path:
    """The run's grants file (outside what a repair snapshot restores, so an undo never brings a grant back)."""
    return Path(run_dir) / "repairs" / "unlocks.json"


def record_path(run_dir) -> Path:
    """The run's plain record of every approval, use, denial and expiry, kept with its repair notes."""
    return Path(run_dir) / "repairs" / "notes" / "alex-approvals.md"


def plain_list(names) -> str:
    """The repairs in plain words: "reset the worktree and replace the spec"."""
    words = [UNLOCKS.get(n, n) for n in names]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def clean_steps(names) -> list[str]:
    """The asked-for unlock names, checked and without repeats; UnlockError when one is not known."""
    if isinstance(names, str):
        names = [n for n in re.split(r"[,\s]+", names) if n]
    if not isinstance(names, (list, tuple)) or not names or not all(isinstance(n, str) for n in names):
        raise UnlockError("Say which repairs to unlock, like --steps reset-worktree.")
    unknown = [n for n in names if n not in UNLOCKS]
    if unknown:
        raise UnlockError(f"'{unknown[0]}' cannot be unlocked. Use one or more of: {', '.join(UNLOCKS)}.")
    return list(dict.fromkeys(names))


def clean_why(why) -> str:
    """The reason as one short printable line; UnlockError otherwise."""
    if not isinstance(why, str) or not why.strip():
        raise UnlockError("Give a reason, in one line.")
    why = why.strip()
    if len(why.splitlines()) != 1 or not why.isprintable():
        raise UnlockError("The reason must be one line of plain text.")
    if len(why) > WHY_MAX:
        raise UnlockError(f"Keep the reason under {WHY_MAX} characters.")
    return scrub.scrub(why)


def _now() -> datetime:
    """The current UTC time (one place, so tests can move the clock)."""
    return datetime.now(timezone.utc)


def _stamp(at: datetime) -> str:
    """A time as the ISO text used in run files."""
    return at.isoformat(timespec="seconds")


def _clock(at: datetime) -> str:
    """A time as Alex reads it: 2026-11-14 14:02 UTC."""
    return at.strftime("%Y-%m-%d %H:%M UTC")


def _record(run_dir: Path, what: str, line: str, **data) -> None:
    """Write one plain line to the run's record and one repair.unlock event."""
    path = record_path(run_dir)
    old = path.read_text(encoding="utf-8") if path.exists() else "# Alex's approvals for repairs\n\n"
    atomic.write_text(path, old + f"- {line}\n")
    events.emit("repair.unlock", project=run_dir.parent.name, run=run_dir.name, what=what, text=line, **data)


def open_requests(run_dir, who: str) -> list[dict]:
    """The asker's unanswered repair-unlock requests on this run."""
    return [g for g in gates.run_gates(run_dir)
            if g.get("kind") == KIND and g["state"] == "open" and g.get("asked_by") == who]


def asker_words(who: str) -> str:
    """Who asked, in words, as the dashboard card says it: "The Phoenix agent" or "A chat in <project>"."""
    if who == "chat:home":
        return "A chat on the home page"
    if who.startswith("chat:"):
        return f"A chat in {who.split(':', 1)[1]}"
    return "The Phoenix agent"


def request(run_dir, steps, why: str, who: str) -> dict:
    """Open a repair-unlock question for Alex; the run itself is not changed. Returns the question."""
    run_dir = Path(run_dir)
    steps, why = clean_steps(steps), clean_why(why)
    if open_requests(run_dir, who):
        raise UnlockError("There is already a request waiting for Alex on this run; wait for Alex's answer.")
    title = f"{asker_words(who)} asks to {plain_list(steps)} on {run_dir.name}: {why}"
    return gates.open_request(run_dir, kind=KIND, title=title, why=why,
                              extra={"unlock_steps": steps, "asked_by": who})


def _load(run_dir: Path) -> dict:
    """The grants file as {"grants": [...]}."""
    data = atomic.read_json(grants_path(run_dir)) or {}
    grants = data.get("grants") if isinstance(data, dict) else None
    return {"grants": [g for g in grants or [] if isinstance(g, dict)]}


def _lock(run_dir: Path) -> state.Lock:
    """The lock that makes using a grant happen once."""
    return state.Lock(Path(run_dir) / "repairs" / "unlocks.lock")


def answered(run_dir, gate: dict, action: str, who: str) -> dict | None:
    """After Alex answered a repair-unlock question: approve writes a one-time grant, deny is recorded. Returns the grant."""
    run_dir = Path(run_dir)
    steps, at = list(gate.get("unlock_steps") or []), _now()
    if action != "approve":
        _record(run_dir, "denied", f"Alex did not allow the agent to {plain_list(steps)}, {_clock(at)}.",
                gate=gate["id"], steps=steps, who=who)
        return None
    grant = {"gate": gate["id"], "run": gate["run"], "steps": steps, "asked_by": gate.get("asked_by"),
             "approved_by": who, "approved_at": _stamp(at),
             "expires_at": _stamp(at + timedelta(minutes=GRANT_MINUTES)), "used_at": None, "expired_at": None}
    with _lock(run_dir):
        data = _load(run_dir)
        data["grants"].append(grant)
        atomic.write_json(grants_path(run_dir), data)
    _record(run_dir, "approved", f"Alex allowed the agent once to {plain_list(steps)}, {_clock(at)} "
            f"(for {GRANT_MINUTES} minutes).", gate=gate["id"], steps=steps, who=who)
    return grant


def _live(grant: dict, at: datetime) -> bool:
    """True when the grant is neither used, nor expired, nor past its time."""
    if grant.get("used_at") or grant.get("expired_at"):
        return False
    try:
        return at < datetime.fromisoformat(grant["expires_at"])
    except (KeyError, TypeError, ValueError):
        return False


def _expire(run_dir: Path, data: dict, at: datetime) -> list[dict]:
    """Mark grants past their time as expired; returns the ones that just ran out."""
    gone = [g for g in data["grants"] if not g.get("used_at") and not g.get("expired_at") and not _live(g, at)]
    for g in gone:
        g["expired_at"] = _stamp(at)
    return gone


def _record_expired(run_dir: Path, gone: list[dict]) -> None:
    """Record each grant that ran out unused."""
    for g in gone:
        try:
            when = _clock(datetime.fromisoformat(g["expires_at"]))
        except (KeyError, TypeError, ValueError):
            when = "its time"
        _record(run_dir, "expired", f"Alex's approval to {plain_list(g.get('steps') or [])} ran out unused at {when}.",
                gate=g.get("gate"), steps=g.get("steps"))


def _matching(data: dict, run_id: str, who: str, needed: list[str], at: datetime) -> dict | None:
    """The first live grant for this run and asker that covers every needed unlock."""
    for g in data["grants"]:
        if g.get("run") == run_id and g.get("asked_by") == who and set(needed) <= set(g.get("steps") or []) \
                and _live(g, at):
            return g
    return None


def find(run_dir, who: str, needed) -> dict | None:
    """The grant that would let these unlocks through now, without using it (a dry run)."""
    run_dir = Path(run_dir)
    if not needed:
        return None
    return _matching(_load(run_dir), run_dir.name, who, list(needed), _now())


def use(run_dir, who: str, needed) -> dict | None:
    """Use a matching grant once: mark it used, record it on the run and return it; None when there is none."""
    run_dir = Path(run_dir)
    needed = list(needed)
    if not needed or not grants_path(run_dir).exists():
        return None
    at = _now()
    with _lock(run_dir):
        data = _load(run_dir)
        gone = _expire(run_dir, data, at)
        grant = _matching(data, run_dir.name, who, needed, at)
        if grant is not None:
            grant.update(used_at=_stamp(at), used_by=who, used_for=needed)
        if gone or grant is not None:
            atomic.write_json(grants_path(run_dir), data)
    _record_expired(run_dir, gone)
    if grant is not None:
        _record(run_dir, "used", f"Repaired by the agent with Alex's approval at {_clock(at)}: {plain_list(needed)}.",
                gate=grant["gate"], steps=needed, who=who)
    return grant


def expire_old(run_dir) -> int:
    """Mark and record every grant of the run that ran out unused; returns how many."""
    run_dir = Path(run_dir)
    if not grants_path(run_dir).exists():
        return 0
    with _lock(run_dir):
        data = _load(run_dir)
        gone = _expire(run_dir, data, _now())
        if gone:
            atomic.write_json(grants_path(run_dir), data)
    _record_expired(run_dir, gone)
    return len(gone)


def records(run_dir) -> list[dict]:
    """Every grant of the run (approved, used or expired), oldest first, for the run page."""
    expire_old(run_dir)
    return _load(Path(run_dir))["grants"]
