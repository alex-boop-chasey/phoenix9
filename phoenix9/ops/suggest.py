"""Ops for suggestions: list the report lines worth a mention, and mark one shown, snoozed or dismissed."""
from phoenix9 import settings, suggest
from phoenix9.ops import common, report

SNOOZE_HOURS = suggest.SNOOZE_HOURS


def mode() -> str:
    """The global suggestions setting: on, strip-only or off."""
    return settings.suggestion_mode()


def list_(strip: bool = False) -> dict:
    """{mode, suggestions}: the lines from a fresh report; the agent's view is empty unless the setting is 'on'."""
    current = mode()
    if current == "off" or (current == "strip-only" and not strip):
        return {"mode": current, "suggestions": []}
    return {"mode": current, "suggestions": suggest.pick(report.status()["text"])}


def mark(key: str, what: str, who: str, hours: float = suggest.SNOOZE_HOURS) -> dict:
    """Mark a key shown, snoozed or dismissed and record the command."""
    try:
        entry = suggest.mark(key, what, hours)
    except ValueError as e:
        raise common.OpsError(str(e)) from None
    common.record_command(who, f"suggest {what}")
    return {"ok": True, "key": key, **entry}
