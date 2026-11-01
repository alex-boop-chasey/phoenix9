"""Ops for `phoenix doctor`: run the health checks with the real adapters."""
from phoenix9 import doctor
from phoenix9.ops import common


def run(adapters=None, *, mode: str = "full") -> dict:
    """Run the checks for a mode (full, for-update or quick); returns {ok, checks: [{name, ok, detail, fix}]}."""
    return doctor.run_checks(adapters or common.make_adapters(), mode)
