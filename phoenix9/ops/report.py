"""Ops for reports: write the daily status report."""
from phoenix9 import statusreport
from phoenix9.ops import common


def status(out: str | None = None) -> dict:
    """Write the status report (to `out`, else HOME/reports/status.md); returns {path, text}."""
    return statusreport.write(common.make_adapters(), out)
