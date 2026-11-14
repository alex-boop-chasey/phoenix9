"""`phoenix service restart api|runner|agent`: hold the harness (runner only), restart through the host adapter, then doctor (B3)."""
import json

import pytest

from fakes import FakeClock
from phoenix9 import atomic, hold, paths
from phoenix9.__main__ import main
from phoenix9.ops import common, service
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)


@pytest.fixture
def host(adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.host.script(["systemctl", "is-active"], out="active\nactive\n")
    adapters.http.script("GET", "http://127.0.0.1:8095/api/health", 200, body=b'{"ok": true}')
    return adapters


def running_run(held=False):
    folder = paths.runs("proj") / "20261106-100000-busy"
    folder.mkdir(parents=True)
    atomic.write_json(folder / "state.json", {"run_id": folder.name, "project": "proj", "status": "running",
                                              "current": {"task": 2, "held": held}, "tasks": {"1": {}, "2": {}}})
    return folder


def restarts(adapters):
    return [c for c in adapters.host.calls if c[:2] == ["systemctl", "restart"]]


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_restart_needs_yes_and_a_known_service(host, capsys):
    code, _, err = run_cmd(capsys, "service", "restart", "runner")
    assert code == 1 and "--yes" in err and restarts(host) == []
    code, _, _ = run_cmd(capsys, "service", "restart", "nginx", "--yes")
    assert code == 2 and restarts(host) == []


def test_api_restart_then_doctor(host, capsys):
    code, out, _ = run_cmd(capsys, "service", "restart", "api", "--yes", "--who", "alex")
    assert code == 0 and restarts(host) == [["systemctl", "restart", "phoenix-api"]]
    assert "Restarted phoenix-api." in out and "services:" in out
    assert "service restart api" in (paths.logs() / "commands.jsonl").read_text()


def test_runner_restart_waits_for_a_task_boundary(host, monkeypatch):
    folder = running_run()

    class ReachesBoundary(FakeClock):
        def sleep(self, s):
            super().sleep(s)
            assert hold.hold_requested()                          # the hold is live while it waits
            st = atomic.read_json(folder / "state.json")
            st["current"]["held"] = True                          # the runner stopped at a task boundary
            atomic.write_json(folder / "state.json", st)

    host.clock = ReachesBoundary()
    r = service.restart("runner", who="alex", yes=True)
    assert r["restarted"] and r["waited"] and restarts(host) == [["systemctl", "restart", "phoenix-runner"]]
    assert r["doctor"]["checks"][0]["name"] == "services"
    assert not (paths.home() / "update" / "hold").exists()       # the hold is released after the restart


def test_runner_restart_gives_up_after_30_minutes(host):
    running_run()
    with pytest.raises(common.OpsError, match="still mid-task after 30 minutes"):
        service.restart("runner", yes=True)
    assert restarts(host) == [] and host.clock.t - 1000.0 >= 30 * 60
    assert not (paths.home() / "update" / "hold").exists()


def test_runner_restart_refused_while_an_update_runs(host):
    from test_updater import other_update
    with other_update():
        with pytest.raises(common.OpsError, match="update of Phoenix is running"):
            service.restart("runner", yes=True)
    assert restarts(host) == []


def test_failed_systemctl_is_a_plain_refusal(host):
    host.host.script(["systemctl", "restart"], rc=1, err="Unit phoenix-api.service not found.")
    with pytest.raises(common.OpsError, match="could not restart phoenix-api: Unit phoenix-api.service not found"):
        service.restart("api", yes=True)


def test_api_route_restarts_the_api_without_waiting(api, host):
    status, body = api("/api/service/api/restart", "POST", POST_HEADERS, {})
    assert status == 400
    status, body = api("/api/service/api/restart", "POST", POST_HEADERS, {"yes": True})
    assert status == 200 and body["data"]["queued"] is True
    assert restarts(host) == [["systemctl", "restart", "--no-block", "phoenix-api"]]


def test_api_route_restarts_the_runner_in_a_job(api, host):
    import time
    status, body = api("/api/service/runner/restart", "POST", POST_HEADERS, {"yes": True})
    assert status == 200
    for _ in range(200):
        job = api(f"/api/jobs/{body['data']['job']}")[1]["data"]
        if job["status"] != "running":
            break
        time.sleep(0.02)
    assert job["kind"] == "restart" and job["status"] == "done" and job["result"]["restarted"]
    assert restarts(host) == [["systemctl", "restart", "phoenix-runner"]]
    assert api("/api/service/nginx/restart", "POST", POST_HEADERS, {"yes": True})[0] == 400


def set_up_agent():
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text("[agent_next]\nuid = 990\n")


def test_agent_restart_is_immediate_and_ends_with_the_doctor(host, capsys):
    set_up_agent()
    code, out, _ = run_cmd(capsys, "service", "restart", "agent", "--yes", "--who", "alex")
    assert code == 0 and restarts(host) == [["systemctl", "restart", "phoenix-agentkit"]]
    assert "Restarted phoenix-agentkit." in out and "services:" in out
    assert "service restart agent" in (paths.logs() / "commands.jsonl").read_text()
    assert not (paths.home() / "update" / "hold").exists()       # no task-boundary wait for the agent


def test_agent_restart_refused_when_not_set_up(host):
    with pytest.raises(common.OpsError, match="not set up yet"):
        service.restart("agent", yes=True)
    assert restarts(host) == []


def test_unknown_service_names_all_three(host):
    with pytest.raises(common.OpsError, match="api, runner or agent"):
        service.restart("nginx", yes=True)


def test_api_route_restarts_the_agent_for_the_dashboard(api, host):
    set_up_agent()
    assert api("/api/service/agent/restart", "POST", POST_HEADERS, {})[0] == 400
    status, body = api("/api/service/agent/restart", "POST", POST_HEADERS, {"yes": True})
    assert status == 200 and body["data"]["service"] == "phoenix-agentkit" and body["data"]["restarted"]
    assert restarts(host) == [["systemctl", "restart", "phoenix-agentkit"]]


def test_api_route_refuses_the_agent_when_not_set_up(api, host):
    status, body = api("/api/service/agent/restart", "POST", POST_HEADERS, {"yes": True})
    assert status == 400 and "not set up" in body["message"] and restarts(host) == []


def test_the_agent_may_not_restart_itself_but_may_restart_the_api(api, host):
    from test_agentaccess import HEADERS, as_agent
    as_agent(api)
    status, body = api("/api/service/agent/restart", "POST", HEADERS, {"yes": True})
    assert status == 400 and "can't restart myself" in body["message"] and restarts(host) == []
    status, body = api("/api/service/api/restart", "POST", HEADERS, {"yes": True})
    assert status == 200 and restarts(host) == [["systemctl", "restart", "--no-block", "phoenix-api"]]
    commands = [json.loads(line) for line in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert any(c.get("who") == "agent" and "service restart api" in json.dumps(c) for c in commands)
