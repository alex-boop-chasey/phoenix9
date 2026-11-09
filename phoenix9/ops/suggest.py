"""Ops for suggestions: list the report lines worth a mention, and mark one shown, snoozed or dismissed."""
from phoenix9 import settings, statusreport, suggest
from phoenix9.ops import common, report

SNOOZE_HOURS = suggest.SNOOZE_HOURS


def mode() -> str:
    """The global suggestions setting: on, strip-only or off."""
    return settings.suggestion_mode()


def _report_text(fresh: bool) -> str:
    """The report text: freshly written (the CLI) or the runner's saved copy (the dashboard; never writes)."""
    return report.status()["text"] if fresh else report.saved()["text"]


def list_(strip: bool = False, fresh: bool = True) -> dict:
    """{mode, notice, suggestions}: the report's lines worth a mention; the agent's view is empty unless the setting
    is 'on'. fresh=False reads the runner's saved report instead of writing a new one."""
    current = mode()
    if current == "off" or (current == "strip-only" and not strip):
        return {"mode": current, "notice": statusreport.NOTICE, "suggestions": []}
    return {"mode": current, "notice": statusreport.NOTICE, "suggestions": suggest.pick(_report_text(fresh))}


def check_key(key: str) -> str:
    """The key when it looks like a suggestion id; OpsError with a plain message otherwise."""
    try:
        return suggest.check_key(key)
    except ValueError as e:
        raise common.OpsError(str(e)) from None


def show(key: str) -> dict:
    """{key, text, section, attention, notice}: one report line by its key (the Agent panel's Ask button names only
    the key); OpsError when the key is not in the current report."""
    try:
        suggest.check_key(key)
    except ValueError as e:
        raise common.OpsError(str(e)) from None
    for row in suggest.parse(_report_text(fresh=True)):
        if row["key"] == key:
            return {**row, "notice": statusreport.NOTICE}
    raise common.OpsError(f"No suggestion {key} in the current status report (it may be dealt with already).")


def mark(key: str, what: str, who: str, hours: float = suggest.SNOOZE_HOURS) -> dict:
    """Mark a key shown, snoozed or dismissed and record the command."""
    try:
        entry = suggest.mark(key, what, hours)
    except ValueError as e:
        raise common.OpsError(str(e)) from None
    common.record_command(who, f"suggest {what}")
    return {"ok": True, "key": key, **entry}
