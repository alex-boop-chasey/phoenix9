"""Run ids, run folders and the run.json record."""
from __future__ import annotations

import random
import string
import time
from pathlib import Path

from phoenix import config
from phoenix.state import load_json, save_json

STATUSES = ("queued", "running", "paused", "done", "failed", "merged", "abandoned")
SUBFOLDERS = ("1-concept", "2-plan", "3-product", "prompts", "logs")

_issued: set[str] = set()


def now_iso() -> str:
    """Return the current UTC time like 2026-10-30T14:05:00Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_run_id() -> str:
    """Return a fresh run id like 20261030-1405-qmzt.

    Never returns the same id twice in one process, and never one whose
    run folder already exists.
    """
    stamp = time.strftime("%Y%m%d-%H%M")
    runs = config.paths().runs
    while True:
        letters = "".join(random.choices(string.ascii_lowercase, k=4))
        run_id = f"{stamp}-{letters}"
        if run_id not in _issued and not (runs / run_id).exists():
            _issued.add(run_id)
            return run_id


def blank_record(run_id: str) -> dict:
    """Return a run.json record with every field present and nothing filled in yet."""
    stamp = now_iso()
    return {
        "run_id": run_id,
        "repo": "",
        "plan_path": "",
        "plan_name": "",
        "plan_sha": "",
        "branch": "",
        "base_sha": "",
        "status": "queued",
        "current_step": None,
        "steps": [],
        "full_suite": None,
        "reason": "",
        "pr_url": "",
        "final_commit": "",
        "finished_at": "",
        "cost_usd": 0.0,
        "sessions": [],
        "started_at": stamp,
        "updated_at": stamp,
    }


def run_dir(run_id: str) -> Path:
    """Return the run's folder, creating it, its sub-folders and a blank run.json if missing."""
    folder = config.paths().runs / run_id
    for name in SUBFOLDERS:
        (folder / name).mkdir(parents=True, exist_ok=True)
    if not (folder / "run.json").exists():
        save_json(folder / "run.json", blank_record(run_id))
    return folder


def load_run(run_id: str) -> dict:
    """Read a run's run.json."""
    return load_json(run_dir(run_id) / "run.json", blank_record(run_id))


def save_run(record: dict) -> None:
    """Write a run's run.json, stamping updated_at. Refuses an unknown status."""
    if record.get("status") not in STATUSES:
        raise ValueError(f"Run status must be one of {', '.join(STATUSES)}, not {record.get('status')!r}.")
    record["updated_at"] = now_iso()
    save_json(run_dir(record["run_id"]) / "run.json", record)
