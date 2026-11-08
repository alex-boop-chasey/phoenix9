"""Tests that repairs show in the run view and the log list."""
from phoenix9 import events, keys
from phoenix9.ops import logs, runs
from tests.helpers import repair_runs as rr


def _setup(tmp_path):
    made = rr.make_run(tmp_path)
    (made["run_dir"] / "repairs/notes").mkdir(parents=True)
    (made["run_dir"] / "repairs/notes/1-fix.md").write_text("# Fix\n")
    (made["run_dir"] / "repairs/report.md").write_text("# Report\n")
    return made


def test_run_view_lists_repairs_from_events(phoenix_env, tmp_path):
    made = _setup(tmp_path)
    events.emit("repair.applied", project=rr.PROJECT, run=rr.RUN, who="alex", note="1-fix.md", title="Fix it",
                steps=[], check_before="bad", check_after="ok", forced=False, rolled_back=False, snapshot="1")
    got = runs.detail(rr.PROJECT, rr.RUN)["repairs"]
    assert [(r["n"], r["who"], r["title"], r["note_id"], r["rolled_back"]) for r in got] == [
        (1, "alex", "Fix it", "1-fix.md", False)]
    assert got[0]["at"]


def test_logs_list_and_read_repair_files(phoenix_env, tmp_path):
    _setup(tmp_path)
    found = {e["id"]: e for e in logs.list_(rr.PROJECT)}
    assert found[f"{rr.RUN}/repairs/notes/1-fix.md"]["kind"] == "repair-note"
    assert found[f"{rr.RUN}/repairs/report.md"]["kind"] == "repair-report"
    assert found[f"{rr.RUN}/repairs/report.md"]["run"] == rr.RUN
    assert logs.read(rr.PROJECT, f"{rr.RUN}/repairs/report.md")["text"] == "# Report\n"


def test_read_scrubs_secrets(phoenix_env, tmp_path):
    made = _setup(tmp_path)
    keys.set_key(rr.PROJECT, "TOKEN", "fake-secret-value-12345", secret=True)
    (made["run_dir"] / "repairs/report.md").write_text("key fake-secret-value-12345\n")
    assert "fake-secret-value-12345" not in logs.read(rr.PROJECT, f"{rr.RUN}/repairs/report.md")["text"]
