"""The `phoenix doctor` command (a stub: Python, HOME and the library; the rest comes later)."""
import os
import sys
import tempfile

from phoenix9 import paths
from phoenix9.cli.output import show
from phoenix9.ops import common


def add(sub, common_parser) -> None:
    """Register doctor."""
    sub.add_parser("doctor", parents=[common_parser], help="check this installation").set_defaults(func=run)


def _home_writable() -> bool:
    home = paths.home()
    if not home.is_dir():
        return False
    try:
        with tempfile.TemporaryFile(dir=home):
            return True
    except OSError:
        return os.access(home, os.W_OK)


def run(args) -> int:
    """Run the basic checks."""
    lib = common.library()
    checks = [("python", sys.version_info >= (3, 12), f"Python {sys.version.split()[0]}"),
              ("home", _home_writable(), f"Phoenix home {paths.home()}"),
              ("library", not lib.problems, f"{len(lib.steps)} steps loaded, {len(lib.problems)} problems")]
    lines = [f"{'ok  ' if ok else 'FAIL'} {what}" for _, ok, what in checks]
    lines.append("The other checks (Docker, Claude, GitHub, services) come later.")
    data = {"ok": all(ok for _, ok, _ in checks),
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}
    show(args, data, "\n".join(lines))
    return 0 if data["ok"] else 1
