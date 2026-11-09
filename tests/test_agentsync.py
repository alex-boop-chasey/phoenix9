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


# ---------------------------------------------------------------- the safety list, in the shapes phoenix.toml really has
import tomllib  # noqa: E402

from phoenix9 import events  # noqa: E402

# The live file's shape (written by `phoenix settings`): the list on ONE line, no trailing comma, tables after it.
SINGLE_LINE = """# Phoenix 9 project settings. Change them with `phoenix settings`, or edit by hand.

preset = "quick"
profile = "platform"
merge = "ask"
max_tries = 3
on_failure = "pause"
services = ["github"]
safety_files = ["one/a.sh", "two/b.py", "three/c.py"]
home_chat_may_answer = ["plan", "merge", "escalation"]

[steps]

[steps.check-writer]
on = false

[steps.red-check]
on = false

[deploy]
with = "none"
mode = "off"
"""


def _setup(text, wanted):
    (paths.install() / "deploy" / "self-project.toml").write_text(
        "safety_files = [" + ", ".join(f'"{w}"' for w in wanted) + "]\n")
    live = paths.projects() / "phoenix9"
    live.mkdir(exist_ok=True)
    (live / "phoenix.toml").write_text(text)
    return live / "phoenix.toml"


def _types():
    return [e["type"] for e in events.read(paths.events())]


def test_single_line_list_stays_valid_toml(folders):
    live = _setup(SINGLE_LINE, ["one/a.sh", "new/d.py", "new/e.py"])
    before = tomllib.loads(SINGLE_LINE)
    assert agentsync.add_safety_files() == ["new/d.py", "new/e.py"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == before["safety_files"] + ["new/d.py", "new/e.py"]
    assert {k: v for k, v in got.items() if k != "safety_files"} == {k: v for k, v in before.items() if k != "safety_files"}
    text = live.read_text()
    assert text.startswith("# Phoenix 9 project settings.")
    assert 'safety_files = ["one/a.sh", "two/b.py", "three/c.py", "new/d.py", "new/e.py"]' in text
    assert agentsync.add_safety_files() == []          # idempotent
    assert live.read_text() == text


def test_multi_line_list(folders):
    live = _setup('preset = "quick"\nsafety_files = [\n  "a",\n  "z",\n]\n\n[deploy]\nmode = "off"\n', ["a", "b"])
    assert agentsync.add_safety_files() == ["b"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == ["a", "z", "b"] and got["deploy"] == {"mode": "off"}


def test_missing_key_goes_to_the_top_level_not_the_last_table(folders):
    live = _setup('preset = "quick"\n\n[deploy]\nwith = "none"\nmode = "off"\n', ["a", "b"])
    assert agentsync.add_safety_files() == ["a", "b"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == ["a", "b"] and got["deploy"] == {"with": "none", "mode": "off"}
    assert agentsync.add_safety_files() == []


def test_broken_file_is_left_alone_and_logged(folders):
    broken = 'preset = "quick"\nsafety_files = ["a", \n[deploy\n'
    live = _setup(broken, ["a", "b"])
    assert agentsync.add_safety_files() == []
    assert live.read_text() == broken
    assert "update.safety_files_skipped" in _types()


def test_non_list_is_left_alone(folders):
    live = _setup('safety_files = "a"\n', ["b"])
    assert agentsync.add_safety_files() == [] and live.read_text() == 'safety_files = "a"\n'


def test_refuses_to_write_when_the_new_text_does_not_read_back(folders, monkeypatch):
    live = _setup(SINGLE_LINE, ["new/d.py"])
    monkeypatch.setattr("phoenix9.settings.render_project", lambda data: 'safety_files = ["x",\n')
    assert agentsync.add_safety_files() == []
    assert live.read_text() == SINGLE_LINE and "update.safety_files_skipped" in _types()


# ---------------------------------------------------------------- symlinks inside the agent folder
def test_symlinked_skills_folder_is_skipped(folders, tmp_path, adapters):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (folders / ".claude").symlink_to(elsewhere)
    assert agentsync.copy_skills() == []
    assert not list(elsewhere.rglob("*")) and "agent.sync_skipped" in _types()


def test_symlinked_pack_folder_is_skipped(folders, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (folders / ".claude" / "skills").mkdir(parents=True)
    (folders / ".claude" / "skills" / "phoenix-agent").symlink_to(elsewhere)
    assert agentsync.copy_skills() == []
    assert not list(elsewhere.iterdir())


def test_symlinked_rules_file_is_skipped(folders, tmp_path):
    target = tmp_path / "other.md"
    target.write_text("other\n")
    (folders / "CLAUDE.md").unlink()
    (folders / "CLAUDE.md").symlink_to(target)
    assert agentsync.refresh_rules() == "skipped"
    assert target.read_text() == "other\n" and (folders / "CLAUDE.md").is_symlink()


def test_symlinked_backups_folder_is_skipped(folders, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (folders / ".phoenix").symlink_to(elsewhere)
    before = (folders / "CLAUDE.md").read_text()
    assert agentsync.refresh_rules() == "skipped"
    assert (folders / "CLAUDE.md").read_text() == before and not list(elsewhere.iterdir())


def test_no_restart_when_rules_skipped(folders, tmp_path, adapters):
    (folders / ".phoenix").symlink_to(tmp_path)
    out = agentsync.refresh_agent(adapters)
    assert out["rules"] == "skipped" and not out["restarted"] and not agentsync.pending_restart()
