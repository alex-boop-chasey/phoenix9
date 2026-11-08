"""Tests for the repair API: the run report and applying a posted repair note."""
import time

from helpers import repair_runs as rr
from phoenix9 import atomic, heartbeat
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

NOTE = f"# Repair {rr.RUN}\n\nWhy: Put the run right\n\n## Steps\n- add a note to task 1: look again\n"


def post(api, body, run=rr.RUN, headers=POST_HEADERS):
    return api(f"/api/repair/{run}/apply", "POST", headers, body)


def test_report_returns_markdown_and_findings(api, phoenix_env, tmp_path):
    made = rr.make_run(tmp_path)
    status, body = api(f"/api/repair/{rr.RUN}/report")
    assert status == 200
    data = body["data"]
    assert data["project"] == rr.PROJECT and "Run report" in data["markdown"]
    assert isinstance(data["findings"], list)
    assert (made["run_dir"] / "repairs/report.md").read_text() == data["markdown"]


def test_report_unknown_run_404(api, phoenix_env):
    assert api("/api/repair/20261108-000000-nope/report")[0] == 404


def test_apply_needs_guard_headers(api, phoenix_env, tmp_path):
    rr.make_run(tmp_path)
    assert post(api, {"note": NOTE}, headers={})[0] == 403
    assert post(api, {"note": NOTE}, headers={"X-Phoenix": "1", "Origin": "http://evil.example"})[0] == 403


def test_apply_parse_error_400_with_line(api, phoenix_env, tmp_path):
    rr.make_run(tmp_path)
    bad = NOTE + "- do a dance\n"
    status, body = post(api, {"note": bad})
    assert status == 400 and "line 7" in body["message"]


def test_apply_bad_body_400(api, phoenix_env, tmp_path):
    rr.make_run(tmp_path)
    assert post(api, {})[0] == 400
    assert post(api, {"note": NOTE, "dry_run": "yes"})[0] == 400
    assert post(api, {"note": NOTE.replace(rr.RUN, "other-run")})[0] == 400


def test_apply_unknown_run_404(api, phoenix_env):
    note = NOTE.replace(rr.RUN, "20261108-000000-nope")
    assert post(api, {"note": note}, run="20261108-000000-nope")[0] == 404


def test_apply_dry_run_changes_nothing(api, phoenix_env, tmp_path):
    made = rr.make_run(tmp_path)
    status, body = post(api, {"note": NOTE, "dry_run": True})
    assert status == 200 and body["data"]["dry_run"] is True
    assert not (made["run_dir"] / "repairs/1").exists()


def test_apply_saves_note_and_applies(api, phoenix_env, tmp_path):
    made = rr.make_run(tmp_path, status="stopped")
    status, body = post(api, {"note": NOTE})
    assert status == 200, body
    assert body["data"]["dry_run"] is False
    saved = list((made["run_dir"] / "repairs/notes").glob("*.md"))
    assert saved and "## Result" in saved[0].read_text()
    assert (made["run_dir"] / "repairs/1").is_dir()


def test_apply_refused_while_runner_walks_409(api, phoenix_env, tmp_path):
    made = rr.make_run(tmp_path, status="running")
    atomic.write_json(made["run_dir"] / "state.json",
                      {"run_id": rr.RUN, "project": rr.PROJECT, "status": "running", "tasks": {}})
    heartbeat.write(time.time())
    status, body = post(api, {"note": NOTE})
    assert status == 409 and "Stop it first" in body["message"]


def test_repair_card_without_note(phoenix_env, tmp_path):
    from phoenix9.ops import cards as ops_cards
    rr.make_run(tmp_path)
    card = ops_cards.build("repair", {"project": rr.PROJECT, "run": rr.RUN})
    assert card["data"]["note"] is None and "failed" in card["data"]["status_line"]
    assert isinstance(card["data"]["findings"], list)


def test_repair_card_shows_note_and_dry_run(phoenix_env, tmp_path):
    from phoenix9.ops import cards as ops_cards
    made = rr.make_run(tmp_path)
    notes = made["run_dir"] / "repairs/notes"
    notes.mkdir(parents=True)
    (notes / "1-put-it-right.md").write_text(NOTE)
    card = ops_cards.build("repair", {"project": rr.PROJECT, "run": rr.RUN, "note": "1-put-it-right.md"})
    note = card["data"]["note"]
    assert note["name"] == "1-put-it-right.md" and note["text"] == NOTE
    assert note["dry_run"]["dry_run"] is True and "steps" in note["dry_run"]
    assert "## Result" not in (notes / "1-put-it-right.md").read_text()
    assert not (made["run_dir"] / "repairs/1").exists()


def test_repair_card_bad_note_and_run(phoenix_env, tmp_path):
    import pytest
    from phoenix9.ops import cards as ops_cards, common
    rr.make_run(tmp_path)
    with pytest.raises(common.NotFound):
        ops_cards.build("repair", {"project": rr.PROJECT, "run": "nope"})
    with pytest.raises(common.OpsError):
        ops_cards.build("repair", {"project": rr.PROJECT, "run": rr.RUN, "note": "../x"})
