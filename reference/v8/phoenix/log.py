"""The Phoenix run log."""
from __future__ import annotations

from phoenix.runs import now_iso, run_dir


def log(run_id: str, text: str) -> None:
    """Add a timestamped line to the run's logs/phoenix.log and print it."""
    line = f"{now_iso()} {text}"
    print(line, flush=True)
    with open(run_dir(run_id) / "logs" / "phoenix.log", "a") as f:
        f.write(line + "\n")
