"""After an install Phoenix's own safety list only grows (moved here from the retired agent refresh)."""
import json
import tomllib

import pytest

from phoenix9 import events, paths
from phoenix9.ops import update as ops_update


@pytest.fixture
def folders(phoenix_env):
    """An installed copy's deploy folder (its self-project.toml is written by each test)."""
    (paths.install() / "deploy").mkdir(parents=True)


def test_safety_files_are_only_added(folders):
    (paths.install() / "deploy" / "self-project.toml").write_text('safety_files = ["a", "b"]\n')
    live = paths.projects() / "phoenix9"
    live.mkdir()
    (live / "phoenix.toml").write_text('preset = "quick"\nsafety_files = [\n  "a",\n  "z",  # mine\n]\nmerge = "ask"\n')
    assert ops_update.add_safety_files() == ["b"]
    got = tomllib.loads((live / "phoenix.toml").read_text())
    assert got["safety_files"] == ["a", "z", "b"] and got["merge"] == "ask"
    assert ops_update.add_safety_files() == []


def test_after_install_command_reports(folders):
    out = ops_update.after_install("test")
    assert out == {"safety_added": []}
    json.dumps(out)


# ---------------------------------------------------------------- the safety list, in the shapes phoenix.toml really has
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
    assert ops_update.add_safety_files() == ["new/d.py", "new/e.py"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == before["safety_files"] + ["new/d.py", "new/e.py"]
    assert {k: v for k, v in got.items() if k != "safety_files"} == {k: v for k, v in before.items() if k != "safety_files"}
    text = live.read_text()
    assert text.startswith("# Phoenix 9 project settings.")
    assert 'safety_files = ["one/a.sh", "two/b.py", "three/c.py", "new/d.py", "new/e.py"]' in text
    assert ops_update.add_safety_files() == []          # idempotent
    assert live.read_text() == text


def test_multi_line_list(folders):
    live = _setup('preset = "quick"\nsafety_files = [\n  "a",\n  "z",\n]\n\n[deploy]\nmode = "off"\n', ["a", "b"])
    assert ops_update.add_safety_files() == ["b"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == ["a", "z", "b"] and got["deploy"] == {"mode": "off"}


def test_missing_key_goes_to_the_top_level_not_the_last_table(folders):
    live = _setup('preset = "quick"\n\n[deploy]\nwith = "none"\nmode = "off"\n', ["a", "b"])
    assert ops_update.add_safety_files() == ["a", "b"]
    got = tomllib.loads(live.read_text())
    assert got["safety_files"] == ["a", "b"] and got["deploy"] == {"with": "none", "mode": "off"}
    assert ops_update.add_safety_files() == []


def test_broken_file_is_left_alone_and_logged(folders):
    broken = 'preset = "quick"\nsafety_files = ["a", \n[deploy\n'
    live = _setup(broken, ["a", "b"])
    assert ops_update.add_safety_files() == []
    assert live.read_text() == broken
    assert "update.safety_files_skipped" in _types()


def test_non_list_is_left_alone(folders):
    live = _setup('safety_files = "a"\n', ["b"])
    assert ops_update.add_safety_files() == [] and live.read_text() == 'safety_files = "a"\n'


def test_refuses_to_write_when_the_new_text_does_not_read_back(folders, monkeypatch):
    live = _setup(SINGLE_LINE, ["new/d.py"])
    monkeypatch.setattr("phoenix9.settings.render_project", lambda data: 'safety_files = ["x",\n')
    assert ops_update.add_safety_files() == []
    assert live.read_text() == SINGLE_LINE and "update.safety_files_skipped" in _types()
