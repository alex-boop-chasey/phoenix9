import re

import pytest

from phoenix import runs
from phoenix.log import log
from phoenix.state import load_json

FIELDS = {"run_id", "repo", "plan_path", "plan_sha", "branch", "base_sha", "status",
          "current_step", "steps", "full_suite", "cost_usd", "sessions",
          "started_at", "updated_at",
          "plan_name", "reason", "pr_url", "final_commit", "finished_at"}   # added in Step 9


def test_new_run_id_format():
    assert re.fullmatch(r"\d{8}-\d{4}-[a-z]{4}", runs.new_run_id())


def test_new_run_id_unique_across_100_calls():
    ids = [runs.new_run_id() for _ in range(100)]
    assert len(set(ids)) == 100


def test_run_dir_creates_folders_and_run_json(phoenix_home):
    rid = runs.new_run_id()
    folder = runs.run_dir(rid)
    assert folder == phoenix_home.resolve() / "runs" / rid
    for name in runs.SUBFOLDERS:
        assert (folder / name).is_dir()
    record = load_json(folder / "run.json", None)
    assert set(record) == FIELDS
    assert record["run_id"] == rid
    assert record["status"] == "queued"


def test_save_run_rejects_unknown_status():
    record = runs.load_run(runs.new_run_id())
    record["status"] = "exploded"
    with pytest.raises(ValueError, match="queued"):
        runs.save_run(record)
    record["status"] = "running"
    runs.save_run(record)
    assert runs.load_run(record["run_id"])["status"] == "running"


def test_log_appends_to_file_and_stdout(capsys):
    rid = runs.new_run_id()
    log(rid, "hello")
    log(rid, "world")
    lines = (runs.run_dir(rid) / "logs" / "phoenix.log").read_text().splitlines()
    assert [l.split(" ", 1)[1] for l in lines] == ["hello", "world"]
    assert "hello" in capsys.readouterr().out
