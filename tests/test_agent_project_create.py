"""Tests for the agent creating a project: allowed shapes start a job, keys and code sources are refused."""
import time

from phoenix9 import events, paths
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist  # noqa: F401  (fixtures)


def form(**kw):
    return {"name": "newone", "description": "A new thing.", "source": {"kind": "template", "template": "python-cli"},
            "profile": "python-script", "new_repo": {"on": False}, "services": [], **kw}


def wait_job(api, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        body = api(f"/api/jobs/{job_id}", headers=HEADERS)[1]
        if body["data"]["status"] != "running":
            return body["data"]
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_agent_create_from_template_starts_a_job_and_records_agent(api):
    as_agent(api)
    status, body = api("/api/projects", "POST", HEADERS, form())
    assert status == 200 and body["data"]["job"]
    job = wait_job(api, body["data"]["job"])
    assert job["status"] == "done", job
    assert (paths.projects() / "newone" / "CLAUDE.md").exists()
    created = [e for e in events.read(paths.events()) if e.get("type") == "project.created"]
    assert created and created[-1]["data"]["who"] == "agent"


def test_body_with_keys_is_refused_and_nothing_is_created(api):
    as_agent(api)
    keys = [{"name": "API_KEY", "value": "sk-nope", "secret": True}]
    status, body = api("/api/projects", "POST", HEADERS, form(keys=keys))
    assert status == 403 and "keys" in body["message"]
    assert not (paths.projects() / "newone").exists()


def test_code_and_repo_sources_and_extra_fields_are_refused(api):
    as_agent(api)
    for extra in ({"source": {"kind": "code", "path": "/srv/x"}}, {"source": {"kind": "repo", "repo": "a/b"}},
                  {"path": "/srv/x"}):
        status, body = api("/api/projects", "POST", HEADERS, form(**extra))
        assert status == 403 and body["message"].startswith("Refused"), extra
    assert not (paths.projects() / "newone").exists()
