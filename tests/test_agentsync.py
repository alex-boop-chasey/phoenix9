"""The post-install agent refresh: knowledge pack, rules file with its kept local section, safety list."""
import json

import pytest

from phoenix9 import agentsync, doctor, paths
from phoenix9.ops import update as ops_update

RULES = "# Rules\n\nnew text\n"
LOCAL = "## Server jobs\n\nkeep this exactly\n\n"


@pytest.fixture
def folders(tmp_path, phoenix_env, monkeypatch, adapters):
    """An installed copy with a pack and rules, an agent folder with old rules and a local section."""
    agent = tmp_path / "agent"
    (agent).mkdir()
    (phoenix_env["home"] / "config").mkdir()
    (phoenix_env["home"] / "config" / "global.toml").write_text(f'[agent]\nfolder = "{agent}"\n')
    src = paths.install() / "deploy" / "agent"
    (src / "skills" / "phoenix-agent").mkdir(parents=True)
    (src / "skills" / "phoenix-agent" / "commands.md").write_text("<!-- phoenix 9.9 inputs abc -->\nbody\n")
    (src / "skills" / "phoenix-agent" / "SKILL.md").write_text("skill\n")
    (src / "agent-rules.md").write_text(RULES)
    (agent / "CLAUDE.md").write_text("# Old\n\n" + LOCAL)
    monkeypatch.setattr("phoenix9.ops.common.make_adapters", lambda: adapters)
    return agent


def test_refresh_copies_pack_and_rebuilds_rules(folders, adapters):
    adapters.host.files["/root/.claude/sessions/1.json"] = ""   # no live agent: nothing to restart
    out = agentsync.refresh_agent(adapters)
    assert out["skills"] == 2 and out["rules"] == "updated" and not out["restarted"]
    assert (folders / ".claude/skills/phoenix-agent/SKILL.md").read_text() == "skill\n"
    text = (folders / "CLAUDE.md").read_text()
    assert text.startswith(RULES) and text.endswith(LOCAL)
    assert len(list((folders / ".phoenix" / "backups").iterdir())) == 1
    assert agentsync.rules_current()[0] and agentsync.pack_current()[0]
    assert agentsync.refresh_rules() == "same"


def test_doctor_lines_fail_before_refresh(folders, adapters):
    assert not agentsync.pack_current()[0] and not agentsync.rules_current()[0]


def test_safety_files_are_only_added(folders, phoenix_env):
    (paths.install() / "deploy" / "self-project.toml").write_text('safety_files = ["a", "b"]\n')
    live = paths.projects() / "phoenix9"
    live.mkdir()
    (live / "phoenix.toml").write_text('preset = "quick"\nsafety_files = [\n  "a",\n  "z",  # mine\n]\nmerge = "ask"\n')
    assert agentsync.add_safety_files() == ["b"]
    import tomllib
    got = tomllib.loads((live / "phoenix.toml").read_text())
    assert got["safety_files"] == ["a", "z", "b"] and got["merge"] == "ask"
    assert agentsync.add_safety_files() == []


def test_after_install_command_reports(folders, phoenix_env):
    out = ops_update.after_install("test")
    assert out["rules"] == "updated" and out["safety_added"] == []
    json.dumps(out)
