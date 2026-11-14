"""Tests for the quick edit and planning session routes: list, finish (a background job), start, show and reply."""
import json
import types

import pytest

from phoenix9 import atomic, edits, paths, plans
from phoenix9.api import server
from phoenix9.ops import common, work
from test_agentaccess import AGENT_UID, HEADERS as AGENT_HEADERS, write_global
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

PR = "https://github.com/o/r/pull/9"


def post(api, path, body=None, headers=POST_HEADERS):
    return api(path, "POST", headers, body if body is not None else {})


def command_whos():
    """(who, command) of every command event written so far."""
    path = paths.events()
    lines = path.read_text().splitlines() if path.exists() else []
    found = [json.loads(x) for x in lines]
    return [(e["data"]["who"], e["data"]["command"]) for e in found if e["type"] == "command"]


def add_edit(edit_id="20261114-fix-typo", project="alpha", status="open", **extra):
    """Write a quick edit record (its folder does not exist, so no git is needed)."""
    rec = {"id": edit_id, "project": project, "title": "Fix the typo", "branch": f"edit/{edit_id}",
           "folder": str(edits.edits_dir() / edit_id), "started": "2026-11-14T10:00:00+00:00", "who": "chat:alpha",
           "status": status, "last_activity": "2026-11-14T10:05:00+00:00", **extra}
    atomic.write_json(edits.record_file(edit_id), rec)
    return rec


def waiting_plan(project="alpha"):
    """Make a planning session that has run once and is waiting on open questions."""
    rec = plans.new_record(project, "Plan the login page", plans.plan_model(), "dashboard")

    def change(r):
        r.update(status="waiting", session_id="11111111-2222-3333-4444-555555555555", open_questions=2,
                 spec=plans.spec_name(r["id"]), report="notes/specs/plan-x.md, 2 open questions")
    return plans.update(rec["id"], change)


def as_agent(monkeypatch):
    """Call as the agent, with every route allowed (step 2 puts these routes on the allowlist)."""
    common.make_adapters().host.peer_uid = AGENT_UID
    write_global(f"[agent_next]\nuid = {AGENT_UID}\n")
    monkeypatch.setattr(server.agentaccess, "route_allowed", lambda method, path: True)


class SyncThread:
    """Runs the background job at once, inside the request, so the test needs no waiting."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class NeverThread(SyncThread):
    """Leaves the job running forever (to see a second finish refused)."""

    def start(self):
        pass


def thread_kind(monkeypatch, cls):
    monkeypatch.setattr(server, "threading", types.SimpleNamespace(Thread=cls))


# ---- quick edits ----

def test_edits_list_only_open_and_stalled_and_no_folder(api):
    make_project("alpha")
    add_edit("20261114-a")
    add_edit("20261114-b", status="stalled")
    add_edit("20261114-c", status="finished", pr=PR)
    add_edit("20261114-d", project="beta")
    status, body = api("/api/edits?project=alpha")
    assert status == 200
    found = body["data"]["edits"]
    assert sorted(e["id"] for e in found) == ["20261114-a", "20261114-b"]
    assert all("folder" not in e for e in found)
    assert set(found[0]) == {"id", "project", "title", "status", "last_activity", "branch", "pr"}
    status, body = api("/api/edits")
    assert len(body["data"]["edits"]) == 3


def test_edits_list_bad_project_refused(api):
    assert api("/api/edits?project=../x")[0] == 400


def test_edit_finish_answers_a_job_that_ends_with_the_pr_link(api, monkeypatch):
    add_edit()
    seen = {}

    def fake_finish(edit_id, message=None, adapters=None, who="cli"):
        seen.update(edit_id=edit_id, message=message, who=who)
        rec = edits.load(edit_id)
        rec.update(status="finished", pr=PR)
        return rec
    monkeypatch.setattr(edits, "finish", fake_finish)
    thread_kind(monkeypatch, SyncThread)
    status, body = post(api, "/api/edits/20261114-fix-typo/finish", {"confirm": True, "message": "Fix it"})
    assert status == 200, body
    job_id = body["data"]["job_id"]
    status, body = api(f"/api/jobs/{job_id}")
    job = body["data"]
    assert job["status"] == "done" and job["kind"] == "edit-finish"
    assert job["result"]["pr"] == PR and "folder" not in job["result"]
    assert seen == {"edit_id": "20261114-fix-typo", "message": "Fix it", "who": "dashboard"}
    assert ("dashboard", "edit finish 20261114-fix-typo") in command_whos()


def test_edit_finish_failure_ends_the_job_failed_with_the_problems(api, monkeypatch):
    add_edit()

    def fake_finish(edit_id, message=None, adapters=None, who="cli"):
        raise edits.EditError("The quick edit is not ready:\n- The edit has no changes yet.")
    monkeypatch.setattr(edits, "finish", fake_finish)
    thread_kind(monkeypatch, SyncThread)
    status, body = post(api, "/api/edits/20261114-fix-typo/finish", {"confirm": True})
    job = api(f"/api/jobs/{body['data']['job_id']}")[1]["data"]
    assert job["status"] == "failed" and "no changes yet" in job["message"]


def test_edit_finish_needs_confirm_and_a_good_id(api):
    add_edit()
    assert post(api, "/api/edits/20261114-fix-typo/finish", {})[0] == 400
    assert post(api, "/api/edits/Bad.Id/finish", {"confirm": True})[0] == 400


def test_edit_finish_one_job_per_edit(api, monkeypatch):
    add_edit()
    add_edit("20261114-other")
    thread_kind(monkeypatch, NeverThread)
    assert post(api, "/api/edits/20261114-fix-typo/finish", {"confirm": True})[0] == 200
    status, body = post(api, "/api/edits/20261114-fix-typo/finish", {"confirm": True})
    assert status == 409 and "already being finished" in body["message"]
    assert post(api, "/api/edits/20261114-other/finish", {"confirm": True})[0] == 200


def test_edit_finish_records_the_agent(api, monkeypatch):
    add_edit()

    def fake_finish(edit_id, message=None, adapters=None, who="cli"):
        return dict(edits.load(edit_id), status="finished", pr=PR)
    monkeypatch.setattr(edits, "finish", fake_finish)
    thread_kind(monkeypatch, SyncThread)
    as_agent(monkeypatch)
    status, body = post(api, "/api/edits/20261114-fix-typo/finish", {"confirm": True}, AGENT_HEADERS)
    assert status == 200, body
    assert ("agent", "edit finish 20261114-fix-typo") in command_whos()


def test_edit_abandon_records_the_real_caller(api, monkeypatch):
    add_edit()
    monkeypatch.setattr(edits, "abandon", lambda edit_id, who: dict(edits.load(edit_id), status="abandoned", who=who))
    as_agent(monkeypatch)
    status, body = post(api, "/api/edits/20261114-fix-typo/abandon", {"confirm": True}, AGENT_HEADERS)
    assert status == 200 and body["data"]["who"] == "agent"
    assert ("agent", "edit abandon 20261114-fix-typo") in command_whos()


# ---- planning sessions ----

def test_plan_start_show_and_list(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/plans", {"brief": "Plan the login page", "model": "haiku"})
    assert status == 200, body
    rec = body["data"]
    assert rec["status"] == "queued" and rec["project"] == "alpha" and rec["spec"] is None
    assert plans.load(rec["id"])["model"] == plans.plan_model()
    assert ("dashboard", "plan start alpha") in command_whos()
    status, body = api(f"/api/plans/{rec['id']}")
    assert status == 200 and body["data"]["brief"] == "Plan the login page" and "report" in body["data"]
    status, body = api("/api/plans?project=alpha")
    assert [p["id"] for p in body["data"]["plans"]] == [rec["id"]]
    assert api("/api/plans?project=beta")[1]["data"]["plans"] == []


def test_plan_list_gives_the_spec_document_id(api):
    make_project("alpha")
    rec = waiting_plan()
    found = api("/api/plans")[1]["data"]["plans"][0]
    assert found["spec"] == f"notes:alpha/specs/plan-{rec['id']}.md"
    assert found["open_questions"] == 2 and found["status"] == "waiting"


def test_plan_bad_or_unknown_id(api):
    assert api("/api/plans/Bad.Id")[0] == 400
    status, body = api("/api/plans/20261114-nothing")
    assert status == 400 and "no planning session" in body["message"]
    assert post(api, "/api/plans/Bad.Id/reply", {"text": "yes"})[0] == 400


def test_plan_start_refusals(api):
    make_project("alpha")
    assert post(api, "/api/projects/alpha/plans", {"brief": " "})[0] == 400
    assert post(api, "/api/projects/nothere/plans", {"brief": "x"})[0] == 400
    assert post(api, "/api/projects/alpha/plans", {"brief": "x"})[0] == 200
    status, body = post(api, "/api/projects/alpha/plans", {"brief": "y"})
    assert status == 400 and "already has a planning session" in body["message"]


def test_agent_refused_on_phoenix9_plan_start(api, monkeypatch):
    make_project("phoenix9")
    as_agent(monkeypatch)
    status, body = post(api, "/api/projects/phoenix9/plans", {"brief": "Plan Phoenix"}, AGENT_HEADERS)
    assert status == 400 and "only Alex can start a planning session" in body["message"]
    assert plans.list_plans("phoenix9") == []
    with pytest.raises(common.OpsError, match="only Alex"):
        work.start_plan("phoenix9", "x", "agent")


def test_agent_plan_start_is_recorded_as_agent(api, monkeypatch):
    make_project("alpha")
    as_agent(monkeypatch)
    status, body = post(api, "/api/projects/alpha/plans", {"brief": "Plan it"}, AGENT_HEADERS)
    assert status == 200, body
    assert plans.load(body["data"]["id"])["who"] == "agent"
    assert ("agent", "plan start alpha") in command_whos()


def test_plan_reply_queues_the_exact_text(api):
    make_project("alpha")
    rec = waiting_plan()
    text = "Use email and password; no social sign-in."
    status, body = post(api, f"/api/plans/{rec['id']}/reply", {"text": text})
    assert status == 200, body
    assert body["data"]["status"] == "queued"
    assert text in plans.prompt_file(rec["id"]).read_text()
    assert ("dashboard", f"plan reply {rec['id']}") in command_whos()


def test_plan_reply_limits(api):
    make_project("alpha")
    rec = waiting_plan()
    assert post(api, f"/api/plans/{rec['id']}/reply", {"text": ""})[0] == 400
    status, body = post(api, f"/api/plans/{rec['id']}/reply", {"text": "x" * 2001})
    assert status == 400 and "too long" in body["message"]
    assert post(api, f"/api/plans/{rec['id']}/reply", {"text": "x" * 2000})[0] == 200
    status, body = post(api, f"/api/plans/{rec['id']}/reply", {"text": "again"})
    assert status == 400 and "already queued" in body["message"]


def test_plan_reply_and_abandon_record_the_agent(api, monkeypatch):
    make_project("alpha")
    rec = waiting_plan()
    as_agent(monkeypatch)
    assert post(api, f"/api/plans/{rec['id']}/reply", {"text": "yes"}, AGENT_HEADERS)[0] == 200
    plans.update(rec["id"], lambda r: r.update(status="waiting"))
    status, body = post(api, f"/api/plans/{rec['id']}/abandon", {"confirm": True}, AGENT_HEADERS)
    assert status == 200, body
    whos = command_whos()
    assert ("agent", f"plan reply {rec['id']}") in whos and ("agent", f"plan abandon {rec['id']}") in whos


def test_plan_text_is_scrubbed(api, monkeypatch):
    make_project("alpha")
    rec = waiting_plan()
    plans.update(rec["id"], lambda r: r.update(report="token ghp_" + "a" * 36))
    body = api(f"/api/plans/{rec['id']}")[1]
    assert "ghp_" + "a" * 36 not in json.dumps(body)
