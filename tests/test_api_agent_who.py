"""Tests that every change route on the agent's allowlist records who made it: `agent` for the agent, `dashboard` otherwise."""
import json

import pytest

from phoenix9 import paths, runs as runs_core, state as run_state
from phoenix9.ops import common, runs as runs_ops
from test_agentaccess import AGENT_UID, HEADERS as AGENT_HEADERS, write_global
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)
from test_api_update_deploy import upd  # noqa: F401  (fixture)
from test_api_writes import add_spec, open_gate
from test_deploy_runner import lib  # noqa: F401  (fixture needed by test_updater's layout users)
from test_updater import layout  # noqa: F401  (fixture)


def start_run():
    """Make project alpha with a spec and a queued run; returns the run id."""
    folder = make_project("alpha")
    add_spec(folder)
    return runs_ops.start("alpha", folder / "notes/specs/login.md")["run_id"]


def running_run():
    """Like start_run, but the run is marked running so it can be paused."""
    run_id = start_run()
    run_state.update(runs_core.find_run(run_id), lambda s: s.__setitem__("status", "running"))
    return run_id


def paused_run():
    """Like start_run, but the run is marked paused so it can be resumed."""
    run_id = start_run()
    run_state.update(runs_core.find_run(run_id), lambda s: s.__setitem__("status", "paused"))
    return run_id


def gate_id():
    """Make project alpha with an open plan question; returns the gate id. (A merge whose run git cannot vouch for
    is Alex's alone, for the agent as for chats: test_agent_refused_on_an_unchecked_merge.)"""
    add_spec(make_project("alpha"))
    return open_gate(kind="plan")[0]["id"]


def merge_gate_id():
    """Make project alpha with an open merge question (tasks not finished, no code repo); returns the gate id."""
    add_spec(make_project("alpha"))
    return open_gate()[0]["id"]


# name -> (path or function making it, body, setup)
def cases():
    """Each allowlisted change route as (label, path maker, body, setup)."""
    def alpha():
        folder = make_project("alpha")
        add_spec(folder)
        return folder
    return [
        ("edit-services", lambda s: "/api/projects/alpha/edit", {"services": []}, alpha),
        ("settings", lambda s: "/api/projects/alpha/settings", {"set": {"steps.notify.on": True}}, alpha),
        ("preset", lambda s: "/api/projects/alpha/settings/preset", {"preset": "quick"}, alpha),
        ("run-start", lambda s: "/api/projects/alpha/runs", {"spec": "specs/login.md"}, alpha),
        ("pause", lambda s: f"/api/runs/{s}/pause", {"now": True}, running_run),
        ("resume", lambda s: f"/api/runs/{s}/resume", {}, paused_run),
        ("stop", lambda s: f"/api/runs/alpha/{s}/stop", {"confirm": True}, start_run),
        ("gate-answer", lambda s: f"/api/gates/{s}/answer", {"action": "approve"}, gate_id),
        ("global-models", lambda s: "/api/global/models", {"steps": {}}, lambda: None),
        ("global-addresses", lambda s: "/api/global/addresses", {"vscode_url": "https://code.example.com"},
         lambda: None),
        ("update-install", lambda s: "/api/update/install", {"yes": True}, lambda: None),
    ]


CASES = cases()


def command_events():
    """The who of every command event written so far."""
    path = paths.events()
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(x)["data"]["who"] for x in lines if json.loads(x)["type"] == "command"]


def run_case(api, case, agent):
    """Make the setup, call the route as the agent or the dashboard, and return (status, body, new command whos)."""
    _, path_of, body, setup = case
    made = setup()
    seed = made if isinstance(made, str) else None
    if agent:
        common.make_adapters().host.peer_uid = AGENT_UID
        write_global(f"[agent_next]\nuid = {AGENT_UID}\n")
    seen = len(command_events())
    status, reply = api(path_of(seed), "POST", AGENT_HEADERS if agent else POST_HEADERS, body)
    return status, reply, command_events()[seen:]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_agent_change_is_recorded_as_agent(api, upd, case):
    """A change through an allowlisted route, called as the agent peer, records who 'agent' and nothing else."""
    status, body, whos = run_case(api, case, agent=True)
    assert status == 200, body
    assert whos and set(whos) == {"agent"}


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_dashboard_change_is_recorded_as_dashboard(api, upd, case):
    """The same call from the dashboard records who 'dashboard'."""
    status, body, whos = run_case(api, case, agent=False)
    assert status == 200, body
    assert whos and set(whos) == {"dashboard"}


def test_agent_gate_answer_is_checked_and_recorded_as_agent(api, upd):
    """The gate answer carries who 'agent' into the answer itself."""
    status, body, _ = run_case(api, CASES[7], agent=True)
    assert status == 200 and body["data"]["who"] == "agent"


def test_agent_refused_on_an_unchecked_merge(api, upd):
    """A merge question whose run is not finished (or git cannot tell) is Alex's alone: the agent is refused."""
    case = ("gate-answer", lambda s: f"/api/gates/{s}/answer", {"action": "approve"}, merge_gate_id)
    status, body, whos = run_case(api, case, agent=True)
    assert status != 200 and "may not answer merge questions" in body["message"]
    assert not whos
