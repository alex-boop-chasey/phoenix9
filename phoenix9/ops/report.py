"""Ops for reports: write the daily status report, or read the copy the runner keeps."""
import time

from phoenix9 import statusreport
from phoenix9.ops import common


def status(out: str | None = None) -> dict:
    """Write the status report (to `out`, else HOME/reports/status.md); returns {path, text}."""
    return statusreport.write(common.make_adapters(), out)


FALLBACK_S = 600
_fallback: dict = {}    # {at, text}: the in-memory report used while no saved copy exists


def saved() -> dict:
    """{path, text, saved}: the copy the runner rewrites every 10 minutes, read without writing anything. When
    there is none yet the report is built in memory (saved False), at most once per 10 minutes, and nothing is
    written."""
    path = statusreport.report_path()
    try:
        return {"path": str(path), "text": path.read_text(encoding="utf-8"), "saved": True}
    except (OSError, UnicodeError):
        pass
    now = time.time()
    if not _fallback or now - _fallback["at"] >= FALLBACK_S:
        _fallback.update(at=now, text=statusreport.build(common.make_adapters()))
    return {"path": str(path), "text": _fallback["text"], "saved": False}
