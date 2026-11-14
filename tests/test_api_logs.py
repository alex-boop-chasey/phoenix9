"""Tests for the logs routes: project lists hold only the project's logs; Phoenix's own logs have their own routes."""
from phoenix9 import paths
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)


def test_project_logs_hold_no_service_logs(api):
    make_project("alpha")
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "updater.log").write_text("installed v1\n")
    status, body = api("/api/logs?project=alpha")
    assert status == 200 and body["data"] == []
    assert api("/api/logs/read?project=alpha&id=logs%2Fupdater.log")[0] == 400


def test_service_logs_list_and_read(api):
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "updater.log").write_text("installed v1\n")
    api("/api/info")      # the API writes its own line to api.log
    status, body = api("/api/service-logs")
    assert status == 200 and {e["id"] for e in body["data"]} == {"api.log", "updater.log"}
    status, body = api("/api/service-logs/read?id=updater.log")
    assert status == 200 and body["data"]["text"] == "installed v1\n" and body["data"]["kind"] == "service"


def test_service_logs_read_refuses_other_ids(api):
    for bad in ("commands.jsonl", "..%2Fconfig%2Fglobal.toml", "events.jsonl", ""):
        assert api(f"/api/service-logs/read?id={bad}")[0] == 400
