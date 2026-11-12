"""The daily report: a short plain-English summary of the last day, built from typed data (no AI, no money figures)."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix9 import allowance, atomic, bell, paths, runs, scrub, settings, statusreport as sr

DAY = 86400.0
MAX_CHARS = 1200
TELEGRAM_MAX = 600
TELEGRAM_END = " More in the bell."
NAMED = 3
MONEY = re.compile(r"(?:(?:US|AU|A)?\$\s?\d[\d,]*(?:\.\d+)?|\bUSD\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|AUD|dollars?)\b)", re.I)
HIDDEN = "(amount hidden)"
QUIET = "Nothing needs you."
KEEP = 30


def strip_money(text) -> str:
    """The text with any dollar figure replaced by '(amount hidden)'."""
    return MONEY.sub(HIDDEN, str(text))


def _clean(text) -> str:
    """Text for the report: secrets masked, money hidden."""
    return strip_money(scrub.scrub(str(text)))


def _line(r: dict) -> str:
    """One run as 'project: spec title (status)'; the title falls back to the run id. Never a cost."""
    name = sr._spec_name(r) or f"build {r['run_id']}"
    return f"{r['project']}: {name} ({r['status']})"


def _recent(now: float) -> list[dict]:
    """Runs that finished or failed in the last 24 hours."""
    out = []
    for r in sr._safe(runs.list_runs) or []:
        age = sr._age(r["updated"], now)
        if r["status"] in ("done", "failed", "stopped") and age is not None and 0 <= age <= DAY:
            out.append(r)
    return out


def _named(label: str, found: list[str]) -> str:
    """'label: a; b; c and 2 more' for a non-empty list, or '' for an empty one."""
    if not found:
        return ""
    shown = "; ".join(found[:NAMED])
    more = f" and {len(found) - NAMED} more" if len(found) > NAMED else ""
    return f"{label} ({len(found)}): {shown}{more}."


def _sections(adapters, now: float) -> list[str]:
    """The report's sections, leaving out the empty ones."""
    recent = _recent(now)
    done = [_line(r) for r in recent if r["status"] == "done"]
    bad = [_line(r) for r in recent if r["status"] != "done"]
    waiting = [i["title"] for i in sr._safe(lambda: bell.items(adapters, now)) or []]
    words = allowance.read(adapters)["words"]
    return [_named("Finished in the last 24 hours", done), _named("Failed or stopped in the last 24 hours", bad),
            _named("Waiting for you", waiting) if waiting else QUIET, f"The agent's allowance: {words}."]


def build(adapters, now: float | None = None) -> str:
    """The daily report text: what finished, what failed, what waits for Alex and the allowance in words."""
    now = time.time() if now is None else now
    parts = [p for p in _sections(adapters, now) if p]
    text = _clean("Phoenix daily report\n" + "\n".join(parts))
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 1].rstrip() + "…"
    return text


def telegram_text(text: str) -> str:
    """A version of the report of at most 600 characters that ends with 'More in the bell.'."""
    flat = " ".join(_clean(text).split())
    room = TELEGRAM_MAX - len(TELEGRAM_END)
    if len(flat) + len(TELEGRAM_END) > TELEGRAM_MAX:
        flat = flat[:room - 1].rstrip() + "…"
    return flat + TELEGRAM_END


def _local(now: float, tz: str) -> datetime:
    """The moment `now` (seconds since 1970) as local time in the named timezone."""
    return datetime.fromtimestamp(now, ZoneInfo(tz))


def due(now: float, cfg: dict, last_sent_date: str | None) -> bool:
    """True once per local day, after the set time has passed on that day; false when disabled."""
    if not cfg.get("enabled"):
        return False
    try:
        local = _local(now, cfg["timezone"])
        hh, mm = (int(x) for x in cfg["time"].split(":"))
    except (KeyError, ValueError, OSError):
        return False
    return last_sent_date != local.date().isoformat() and (local.hour, local.minute) >= (hh, mm)


def _dir() -> Path:
    return paths.home() / "reports" / "daily"


def _state_file() -> Path:
    return paths.home() / "reports" / "daily-state.json"


def _save(date: str, text: str) -> None:
    """Write the report for that date atomically and keep only the newest 30."""
    atomic.write_text(_dir() / f"{date}.md", text)
    for old in sorted(_dir().glob("*.md"))[:-KEEP]:
        old.unlink(missing_ok=True)


def latest() -> dict | None:
    """{date, text} of the newest saved report, or None."""
    try:
        files = sorted(_dir().glob("*.md"))
        return {"date": files[-1].stem, "text": files[-1].read_text()} if files else None
    except OSError:
        return None


def send_if_due(adapters) -> bool:
    """When the report is due: build and save it, send the short version, record the date. Never raises."""
    try:
        cfg = settings.report_settings()
        now = adapters.clock.now()
        last = (atomic.read_json(_state_file(), {}) or {}).get("last_sent_date")
        if not due(now, cfg, last):
            return False
        date = _local(now, cfg["timezone"]).date().isoformat()
        text = build(adapters, now)
        _save(date, text)
        adapters.notify.send(telegram_text(text))
        atomic.write_json(_state_file(), {"last_sent_date": date})
        return True
    except Exception:  # noqa: BLE001 - the report must never stop the runner
        return False
