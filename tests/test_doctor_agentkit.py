"""Tests for the doctor lines about the new agent, using the fake adapter."""
import json
import os
import re

import pytest

from phoenix9 import doctor, paths

NAMES = ("agentkit-service", "agentkit-key", "agentkit-spend")
KEY = os.environ.get("ANTHROPIC_API_KEY") or "test-key-value-not-a-real-key"


@pytest.fixture
def env(adapters, phoenix_env):
    """Fakes with [agent_next] set up, a running service, a key and plenty of allowance."""
    (paths.config()).mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text('[agent_next]\nuid = 990\n')
    adapters.host.script(["systemctl", "is-active", "phoenix-agentkit"], 0, "active\n")
    answers = {"/status": {"running": True, "key_present": True, "pack": "phoenix", "model": "m", "api_key": KEY},
               "/spend": {"month": "2026-11", "used_share": 0.1, "state": "plenty"}}

    def get_json(path):
        return answers[path]
    adapters.agentnext.get_json = get_json
    adapters.answers = answers
    return adapters


def lines(adapters, mode="full"):
    data = doctor.run_checks(adapters, mode)
    return {c["name"]: c for c in data["checks"] if c["name"] in NAMES}


def test_all_good(env):
    for mode in ("quick", "full"):
        got = lines(env, mode)
        assert set(got) == set(NAMES) and all(c["ok"] for c in got.values())
        assert "plenty left this month" in got["agentkit-spend"]["detail"]


def test_not_set_up_is_not_a_failure(adapters, phoenix_env):
    got = lines(adapters)
    assert all(c["ok"] and "not set up yet" in c["detail"] for c in got.values())


def test_service_not_active(env):
    env.host.script(["systemctl", "is-active", "phoenix-agentkit"], 3, "inactive\n")
    assert not lines(env)["agentkit-service"]["ok"]


def test_service_not_answering(env):
    env.agentnext.get_json = lambda path: (_ for _ in ()).throw(doctor.agentnext.AgentUnavailable("down"))
    got = lines(env)
    assert not got["agentkit-service"]["ok"] and not got["agentkit-key"]["ok"] and not got["agentkit-spend"]["ok"]


def test_key_missing(env):
    env.answers["/status"]["key_present"] = False
    assert not lines(env)["agentkit-key"]["ok"]


def test_spend_states(env):
    for state, ok, words in (("plenty", True, "plenty left"), ("low", True, "getting low"), ("used_up", False, "used up this month")):
        env.answers["/spend"] = {"month": "2026-11", "used_share": 0.9, "state": state}
        line = lines(env)["agentkit-spend"]
        assert line["ok"] is ok and words in line["detail"]
    env.answers["/spend"]["state"] = "low"
    assert "Warning" in lines(env)["agentkit-spend"]["detail"]


def test_no_money_or_key_in_any_line(env):
    for state in ("plenty", "low", "used_up"):
        env.answers["/spend"] = {"state": state, "used_share": 0.95, "cost_usd": 94.5}
        text = json.dumps(doctor.run_checks(env, "full")["checks"])
        agent_lines = json.dumps(list(lines(env).values()))
        assert "$" not in agent_lines and KEY not in text
        assert not re.search(r"\d", agent_lines.replace("phoenix-agentkit", ""))
