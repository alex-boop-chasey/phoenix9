"""The `phoenix project keys` and `services` commands."""
import io
import json

import pytest

from phoenix9 import keys, paths
from phoenix9.__main__ import main

SECRET = "sk-test-VERY-secret-value-12345"


@pytest.fixture
def demo(phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "phoenix.toml").write_text('preset = "quick"\n')
    return folder


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_set_reads_stdin_not_argv(capsys, demo, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, out, err = run_cmd(capsys, "project", "keys", "demo", "set", "API_KEY", "--secret")
    assert code == 0 and SECRET not in out + err
    assert keys.secret_values("demo") == [SECRET]
    f = demo.parent / "value.txt"
    f.write_text("from-a-file-value\n")
    assert run_cmd(capsys, "project", "keys", "demo", "set", "OTHER", "--from-file", str(f))[0] == 0
    assert keys.container_env("demo")["OTHER"] == "from-a-file-value"


def test_cli_list_masks_secrets(capsys, demo):
    keys.set_key("demo", "API_KEY", SECRET, True)
    keys.set_key("demo", "PUBLIC_URL", "https://x.test", False)
    keys.add_empty("demo", "LATER", True)
    code, out, _ = run_cmd(capsys, "project", "keys", "demo")
    assert code == 0 and SECRET not in out
    assert "••••••" in out and "(empty)" in out and "https://x.test" in out


def test_cli_json(capsys, demo):
    keys.set_key("demo", "API_KEY", SECRET, True)
    code, out, _ = run_cmd(capsys, "project", "keys", "demo", "--json")
    rows = json.loads(out)
    assert code == 0 and rows[0]["name"] == "API_KEY" and SECRET not in out
    code, out, _ = run_cmd(capsys, "project", "services", "demo", "--set", "resend", "--json", "--who", "tester")
    assert json.loads(out)["services"] == ["resend"]
    code, out, _ = run_cmd(capsys, "project", "services", "demo", "--json")
    assert json.loads(out)["chosen"] == ["resend"] and len(json.loads(out)["available"]) == 9
    code, out, err = run_cmd(capsys, "project", "services", "demo", "--set", "bogus")
    assert code == 1 and "Unknown service" in err


def test_cli_remove_needs_yes(capsys, demo):
    keys.set_key("demo", "API_KEY", SECRET, True)
    code, _, err = run_cmd(capsys, "project", "keys", "demo", "remove", "API_KEY")
    assert code == 1 and "--yes" in err and keys.secret_values("demo")
    assert run_cmd(capsys, "project", "keys", "demo", "remove", "API_KEY", "--yes")[0] == 0
    assert keys.secret_values("demo") == []
    assert run_cmd(capsys, "project", "keys", "demo", "remove", "API_KEY", "--yes")[0] == 1


def test_command_event_has_no_value(capsys, demo, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET))
    run_cmd(capsys, "project", "keys", "demo", "set", "API_KEY", "--secret", "--who", "alex")
    commands = (paths.logs() / "commands.jsonl").read_text()
    assert "API_KEY" in commands and '"who": "alex"' in commands
    for f in (paths.events(), paths.logs() / "commands.jsonl", demo / "notes" / "changelog.md"):
        assert SECRET not in f.read_text()
    assert '"type": "command"' in paths.events().read_text()
    assert "project.changed" in paths.events().read_text()
