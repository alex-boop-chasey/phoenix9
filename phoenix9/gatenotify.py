"""Telling Alex a question is waiting: one message (after a quiet wait), reminders while it stays open (no replies by message)."""
from pathlib import Path

from . import addresses, atomic, gates, paths, scrub, settings

MAX_REMINDERS = 6
QUESTION_CHARS = 200
DEFAULT_REMIND_HOURS = 4
DEFAULT_QUIET_MINUTES = 10


def _record_path(run_dir, gate_id: str) -> Path:
    """The small file (next to the gate) that remembers what was sent for it, so a restart never repeats it."""
    return Path(run_dir) / "gates" / f"{gate_id}.notified"


def read_record(run_dir, gate_id: str) -> dict | None:
    """What was sent for this gate ({first, reminders, last}), or None when nothing was."""
    got = atomic.read_json(_record_path(run_dir, gate_id))
    return got if isinstance(got, dict) else None


def _link(project: str) -> str:
    """The dashboard page where the project's questions are answered; '' when no dashboard address is set."""
    url = addresses._table().get("dashboard_url")
    if not isinstance(url, str) or not url.strip():
        return ""
    return f"{url.strip().rstrip('/')}/p/{project}/build"


def _run_title(run_dir, gate: dict) -> str:
    """The run's title (from its spec), else its id."""
    spec = atomic.read_json(Path(run_dir) / "spec.json") or {}
    return str(spec.get("title") or gate["run"])


def _question(gate: dict) -> str:
    """The question in one scrubbed line, cut to about 200 characters (the title only: never plan text or files)."""
    line = " ".join(str(gate.get("title") or "").split())
    line = scrub.scrub(line)
    return line if len(line) <= QUESTION_CHARS else line[:QUESTION_CHARS - 1].rstrip() + "…"


def message(run_dir, gate: dict, reminder: int = 0) -> str:
    """The plain message for a waiting question; `reminder` > 0 makes it the nth reminder."""
    link = _link(gate["project"])
    where = f"Answer it here: {link}" if link else "Open the dashboard and look under Needs you."
    head = f"Reminder {reminder} of {MAX_REMINDERS}: " if reminder else ""
    text = (f"{head}{gate['project']}, run {_run_title(run_dir, gate)} is waiting for you: "
            f"{_question(gate)}. {where}")
    return scrub.scrub(text)


def _send(adapters, text: str) -> None:
    """Send through the notify adapter; a failure to tell never stops the run."""
    try:
        adapters.notify.send(text)
    except Exception:  # noqa: BLE001 - telling Alex must not stop a build
        pass


def mark_sent(adapters, run_dir, gate: dict) -> None:
    """Remember that Alex was told about this question just now (the first message went another way)."""
    now = adapters.clock.now()
    atomic.write_json(_record_path(run_dir, gate["id"]), {"first": now, "reminders": 0, "last": now})


def announce(adapters, run_dir, gate: dict) -> None:
    """Send the one 'a question is waiting' message for a newly opened gate (recorded first, so never twice).

    With `[notify] quiet_minutes` above 0 the message is held instead: the runner loop sends it only if
    the question is still open after that wait (`send_held`), so a question a chat answers soon stays quiet.
    """
    if quiet_minutes() > 0:
        atomic.write_json(_record_path(run_dir, gate["id"]), {"held": adapters.clock.now(), "reminders": 0})
        return
    mark_sent(adapters, run_dir, gate)
    _send(adapters, message(run_dir, gate))


def announce_auto_approved(adapters, run_dir, gate: dict) -> None:
    """Tell Alex the plan was approved by the project setting instead of by a person."""
    mark_sent(adapters, run_dir, gate)
    _send(adapters, scrub.scrub(f"{gate['project']}, run {_run_title(run_dir, gate)}: "
                                "plan approved automatically (project setting)"))


def remind_hours() -> float:
    """The global `[notify] remind_hours` (default 4; 0 = no reminders); a bad value means the default."""
    table = settings.read_global().get("notify")
    value = table.get("remind_hours") if isinstance(table, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return DEFAULT_REMIND_HOURS
    return value


def quiet_minutes() -> float:
    """The global `[notify] quiet_minutes` (default 10; 0 = tell at once); a bad value means the default."""
    table = settings.read_global().get("notify")
    value = table.get("quiet_minutes") if isinstance(table, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return DEFAULT_QUIET_MINUTES
    return value


def _send_held_one(adapters, gate: dict, minutes: float, now: float) -> bool:
    """Send this open gate's held first message once its quiet wait is over; True when it did."""
    run_dir = paths.runs(gate["project"]) / gate["run"]
    record = read_record(run_dir, gate["id"])
    if record is None or "held" not in record:
        return False                      # already told (or never announced)
    if now - float(record.get("held") or 0) < minutes * 60:
        return False
    mark_sent(adapters, run_dir, gate)    # recorded first, so a restart never sends it twice
    _send(adapters, message(run_dir, gate))
    return True


def send_held(adapters) -> int:
    """Send the held first message of every question still open after the quiet wait; returns how many went out."""
    minutes = quiet_minutes()
    now = adapters.clock.now()
    return sum(_send_held_one(adapters, g, minutes, now) for g in gates.list_gates(open_only=True))


def _remind_one(adapters, gate: dict, hours: float, now: float) -> bool:
    """Send this open gate's next reminder if one is due; True when it did."""
    run_dir = paths.runs(gate["project"]) / gate["run"]
    record = read_record(run_dir, gate["id"])
    if record is None or "held" in record or int(record.get("reminders") or 0) >= MAX_REMINDERS:
        return False                      # not told yet (none or held) or all reminders already sent
    if now - float(record.get("last") or 0) < hours * 3600:
        return False
    count = int(record.get("reminders") or 0) + 1
    atomic.write_json(_record_path(run_dir, gate["id"]), {**record, "reminders": count, "last": now})
    _send(adapters, message(run_dir, gate, count))
    return True


def send_reminders(adapters) -> int:
    """Remind about every question that is still open and due; returns how many reminders went out."""
    hours = remind_hours()
    if hours <= 0:
        return 0
    now = adapters.clock.now()
    return sum(_remind_one(adapters, g, hours, now) for g in gates.list_gates(open_only=True))
