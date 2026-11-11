"""Tests for the seven read routes the guided flows use, called as the agent."""
from phoenix9 import agentaccess
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)


def test_each_read_route_answers_200_for_the_agent(api):
    make_project("alpha")
    as_agent(api)
    for method, path, body in (
            ("GET", "/api/projects/check-name?name=fresh", None),
            ("GET", "/api/library/templates", None),
            ("GET", "/api/library/profiles", None),
            ("GET", "/api/library/services", None),
            ("GET", "/api/projects/alpha/specs", None),
            ("POST", "/api/projects/alpha/plan", {}),
            ("POST", "/api/projects/alpha/plan", {"overrides": {}})):
        status, reply = api(path, method, HEADERS, body) if body is not None else api(path, headers=HEADERS)
        assert status == 200 and reply["ok"], path


def test_job_status_answers_200_and_refuses_unsafe_ids(api):
    as_agent(api)
    assert api("/api/jobs/abc123abc123", headers=HEADERS)[0] == 404   # allowed route, no such job
    for bad in ("../info", "ab/cd", "..", "ABC", "x%2F..%2Finfo"):
        status, body = api(f"/api/jobs/{bad}", headers=HEADERS)
        assert status in (403, 404) and not body["ok"], bad
    assert not agentaccess.route_allowed("GET", "/api/jobs/ab/../info")
    assert not agentaccess.route_allowed("GET", "/api/jobs/ab/cd")
