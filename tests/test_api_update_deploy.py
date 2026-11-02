"""Tests for the update and deploy endpoints of the dashboard API, on a temp install and fake host."""
import pytest

from phoenix9 import atomic, paths, updater
from phoenix9.ops import common
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)
from test_api_writes import wait_job
from test_deploy_runner import lib, make_project, script  # noqa: F401  (fixtures)
from test_updater import layout  # noqa: F401  (fixture: origin + temp install at v9.0)


def post(api, path, body=None):
    return api(path, "POST", POST_HEADERS, body if body is not None else {})


@pytest.fixture
def upd(layout, adapters, monkeypatch):
    """An installed v9.0 with v9.2 as newest, and the API's adapters replaced by the same fakes."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    updater.status(adapters, refresh=True)
    return adapters


def test_get_update_status(api, upd):
    status, body = api("/api/update")
    assert status == 200 and body["data"]["installed"]["tag"] == "v9.0" and body["data"]["newest"] == "v9.2"
    status, body = api("/api/update?refresh=1")
    assert status == 200 and body["data"]["update_available"] is True and "log_tail" in body["data"]


def test_info_lists_update_endpoints(api, upd):
    update = api("/api/info")[1]["data"]["update"]
    assert update["endpoints"] == {"install": "update/install", "rollback": "update/rollback"}
    assert update["available"] is True and update["can_install"] is True


def test_install_needs_guard_and_yes(api, upd):
    assert api("/api/update/install", "POST", {}, {"yes": True})[0] == 403
    status, body = post(api, "/api/update/install", {})
    assert status == 400 and "--yes" in body["message"]
    assert not (paths.home() / "update" / "request.json").exists()


def test_install_queues_via_ops(api, upd):
    status, body = post(api, "/api/update/install", {"yes": True})
    assert status == 200 and body["data"]["ok"] and body["data"]["queued"] and body["data"]["tag"] == "v9.2"
    assert ["systemctl", "start", "--no-block", "phoenix9-update.service"] in upd.host.calls
    assert atomic.read_json(paths.home() / "update" / "request.json")["who"] == "dashboard"


def test_rollback_needs_yes(api, upd):
    status, body = post(api, "/api/update/rollback", {})
    assert status == 400 and "--yes" in body["message"]
    assert not (paths.home() / "update" / "request.json").exists()
    assert post(api, "/api/update/rollback", {"yes": True})[0] in (200, 400)


def test_update_log(api, upd):
    post(api, "/api/update/install", {"yes": True, "tag": "v9.1"})
    status, body = api("/api/update/log?lines=5")
    assert status == 200 and any("asked for install v9.1" in line for line in body["data"]["lines"])


def test_deploy_job_runs_and_reports(api, phoenix_env, lib, script, adapters, monkeypatch):  # noqa: F811
    make_project(phoenix_env)
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    status, body = post(api, "/api/projects/demo/deploy", {})
    assert status == 400
    status, body = post(api, "/api/projects/demo/deploy", {"yes": True})
    assert status == 200
    job = wait_job(api, body["data"]["job"])
    assert job["kind"] == "deploy" and job["status"] == "done" and job["result"]["url"] == "https://demo.example"
    assert post(api, "/api/projects/nope/deploy", {"yes": True})[0] == 404


def test_deploys_status(api, phoenix_env, lib, script, adapters, monkeypatch):  # noqa: F811
    make_project(phoenix_env)
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    wait_job(api, post(api, "/api/projects/demo/deploy", {"yes": True})[1]["data"]["job"])
    status, body = api("/api/projects/demo/deploys")
    assert status == 200 and body["data"]["live_url"] == "https://demo.example" and len(body["data"]["recent"]) == 1


def test_health_endpoint(api):
    status, body = api("/api/health")
    assert status == 200 and body["data"]["ok"] is True and body["data"]["version"] and "tag" in body["data"]
