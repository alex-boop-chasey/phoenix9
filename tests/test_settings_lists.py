"""`phoenix settings add|remove <project> <list key> <item>`: one item in or out of a list setting (B4)."""
import json
import tomllib

import pytest

from phoenix9 import events, paths
from phoenix9.__main__ import main


@pytest.fixture
def demo(phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("# Demo\n")
    (folder / "phoenix.toml").write_text('profile = "python-script"\nsafety_files = ["phoenix9/runner.py"]\n')
    return folder


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def saved(demo) -> dict:
    return tomllib.loads((demo / "phoenix.toml").read_text())


def test_add_appends_one_item_and_records_it(demo, capsys):
    code, out, _ = run_cmd(capsys, "settings", "add", "demo", "safety_files", "phoenix9/gates.py", "--who", "alex")
    assert code == 0 and "Added phoenix9/gates.py to safety_files in demo." in out
    assert saved(demo)["safety_files"] == ["phoenix9/runner.py", "phoenix9/gates.py"]
    changed = [e for e in events.read(paths.events()) if e["type"] == "settings.changed"]
    assert changed and changed[-1]["data"]["key"] == "safety_files" and changed[-1]["data"]["who"] == "alex"
    log = (paths.logs() / "commands.jsonl").read_text()
    assert "settings add demo safety_files" in log and '"who": "alex"' in log
    assert "added phoenix9/gates.py to safety_files" in (demo / "notes" / "changelog.md").read_text()


def test_remove_takes_one_item_out(demo, capsys):
    code, out, _ = run_cmd(capsys, "settings", "remove", "demo", "safety_files", "phoenix9/runner.py", "--json")
    assert code == 0 and json.loads(out)["value"] == []
    assert saved(demo)["safety_files"] == []


def test_add_starts_from_the_effective_list(demo, capsys):
    code, _, _ = run_cmd(capsys, "settings", "add", "demo", "services", "resend")
    assert code == 0 and saved(demo)["services"] == ["resend"]


def test_refusals(demo, capsys):
    code, _, err = run_cmd(capsys, "settings", "add", "demo", "max_tries", "4")
    assert code == 1 and "not a list" in err
    code, _, err = run_cmd(capsys, "settings", "add", "demo", "safety_files", "phoenix9/runner.py")
    assert code == 1 and "already" in err
    code, _, err = run_cmd(capsys, "settings", "remove", "demo", "safety_files", "nope.py")
    assert code == 1 and "is not in" in err
    code, _, err = run_cmd(capsys, "settings", "add", "demo", "bogus", "x")
    assert code == 1 and "unknown key 'bogus'" in err
    code, _, err = run_cmd(capsys, "settings", "add", "demo", "steps.builder.advisor.when", "sometimes")
    assert code == 1 and "must be one of" in err
    assert saved(demo)["safety_files"] == ["phoenix9/runner.py"]
