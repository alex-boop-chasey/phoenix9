"""Tests for the agent service's deploy files: the unit's settings, no root, no key in the environment, a quiet token."""
import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy" / "agentkit"
UNIT = (DEPLOY / "phoenix-agentkit.service").read_text()
SETUP = (DEPLOY / "setup.sh").read_text()
README = (DEPLOY / "README.md").read_text()


def unit_lines():
    """The unit's non-comment lines."""
    return [l.strip() for l in UNIT.splitlines() if l.strip() and not l.strip().startswith("#")]


def test_runs_as_its_own_user_not_root():
    """The unit names the agent user and never root."""
    lines = unit_lines()
    assert "User=phoenix-agentkit" in lines
    assert not any(re.match(r"(User|Group)=(root|0)$", l) for l in lines)


def test_exec_start_uses_the_venv_on_the_installed_code():
    """The program comes from the agent's venv and runs the installed copy."""
    lines = unit_lines()
    start = next(l for l in lines if l.startswith("ExecStart="))
    assert start.split("=", 1)[1].startswith("/var/lib/phoenix9/agentkit/venv/bin/python")
    assert "WorkingDirectory=/opt/phoenix9/agentkit" in lines
    assert not any("sh -c" in l or "/bin/sh" in l or "/bin/bash" in l for l in lines)


def test_hardening_settings():
    """The unit is locked down and may write only to its own folder."""
    lines = unit_lines()
    for needed in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes"):
        assert needed in lines
    writable = [l for l in lines if l.startswith("ReadWritePaths=")]
    assert writable == ["ReadWritePaths=/var/lib/phoenix9/agentkit"]


def test_no_key_in_the_environment():
    """No Environment or EnvironmentFile line, so the key is never put in the environment."""
    lines = unit_lines()
    assert not any(l.startswith(("Environment", "PassEnvironment")) for l in lines)
    assert "ANTHROPIC_API_KEY" not in UNIT + SETUP


def test_setup_never_echoes_or_touches_the_key_or_token():
    """setup.sh prints no token, never reads it back, and never writes the api-key file."""
    for line in SETUP.splitlines():
        code = line.split("#", 1)[0]
        if re.match(r"\s*(echo|printf)\b", code):
            assert "token" not in code.lower().replace("token_file", "") or "$" not in code
        assert not re.search(r"cat\s+\S*token", code)
    assert "chmod 640" in SETUP and "root:$USER_NAME" in SETUP
    assert not re.search(r">\s*\S*api-key", SETUP)
    assert not re.search(r"(cp|mv|chmod|chown|touch|tee)\b[^\n]*api-key", SETUP)


def test_setup_is_safe_to_repeat():
    """setup.sh keeps an existing config and token, and refuses to run unless root."""
    assert 'if [ ! -f "$AGENT_DIR/config.toml" ]' in SETUP
    assert 'if [ ! -s "$AGENT_DIR/token" ]' in SETUP
    assert "id -u" in SETUP and "nologin" in SETUP and "chmod 750" in SETUP
    assert "agent_next" in SETUP and "token_file" in SETUP and "uid" in SETUP


def test_addresses():
    """The agent listens on 8097 and Phoenix is at 8095; 8090 is never used."""
    everything = UNIT + SETUP + README
    assert "8097" in README
    assert "http://127.0.0.1:8095" in README
    assert "8090" not in everything


def test_readme_has_no_dollar_amounts():
    """The README shows no prices or dollar figures."""
    assert "$" not in README
    assert not re.search(r"\busd\b", README, re.I)
    assert "CHECK BEFORE USE" in README and "api-key" in README and "phoenix doctor" in README
