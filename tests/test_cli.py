"""Tests for the phoenix command line: every command, with temp HOME and projects."""
import json

import pytest

from phoenix9 import gates, paths
from phoenix9.__main__ import main
from phoenix9.ops import common

SPEC = """# Add a hello script
Project: demo

## Task 1: Hello
Make a script called hello.py that prints hello.
Done when:
- `python3 hello.py`
"""


@pytest.fixture
def demo(phoenix_env, tmp_path, monkeypatch):
    """A project called demo, a spec file, and fake adapters for ops."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    folder = phoenix_env["projects"] / "demo"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("# Demo\n\nA small demo project.\nSecond line.\n\nOther.\n")
    (folder / "phoenix.toml").write_text('preset = "quick"\n')
    spec = tmp_path / "spec.md"
    spec.write_text(SPEC)
    return {"folder": folder, "spec": str(spec), "fakes": fakes}


def run_cmd(capsys, *argv):
    """Run main and return (exit code, stdout, stderr)."""
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def start_run(capsys, demo):
    code, out, _ = run_cmd(capsys, "run", "start", "demo", "--spec", demo["spec"], "--json")
    assert code == 0
    return json.loads(out)["run_id"]


def test_help_lists_every_group(capsys):
    code, out, _ = run_cmd(capsys, "--help")
    assert code == 0
    for group in ("run", "gate", "settings", "steps", "profiles", "project", "doctor"):
        assert group in out


def test_run_start_status_list_log(capsys, demo):
    run_id = start_run(capsys, demo)
    code, out, _ = run_cmd(capsys, "run", "status", run_id)
    assert code == 0 and "queued" in out and "Traceback" not in out
    assert json.loads(run_cmd(capsys, "run", "status", run_id, "--json")[1])["run_id"] == run_id
    code, out, _ = run_cmd(capsys, "run", "list")
    assert run_id in out
    assert json.loads(run_cmd(capsys, "run", "list", "demo", "--json")[1])[0]["run_id"] == run_id
    code, out, _ = run_cmd(capsys, "run", "log", run_id)
    assert code == 0 and "run.queued" in out
    log = json.loads(run_cmd(capsys, "run", "log", run_id, "--step", "x", "--task", "1", "--json")[1])
    assert log["events"] == []


def test_run_start_with_preset_and_bad_spec(capsys, demo, tmp_path):
    code, out, _ = run_cmd(capsys, "run", "start", "demo", "--spec", demo["spec"], "--preset", "full", "--json")
    assert code == 0
    folder = next(paths.runs("demo").iterdir())
    assert json.loads((folder / "overrides.json").read_text()) == {"preset": "full"}
    bad = tmp_path / "bad.md"
    bad.write_text("nothing useful\n")
    code, _, err = run_cmd(capsys, "run", "start", "demo", "--spec", str(bad))
    assert code == 1 and "problems" in err and "Traceback" not in err


def test_run_stop_needs_yes(capsys, demo):
    run_id = start_run(capsys, demo)
    code, _, err = run_cmd(capsys, "run", "stop", run_id)
    assert code == 1 and "--yes" in err
    assert json.loads(run_cmd(capsys, "run", "status", run_id, "--json")[1])["status"] == "queued"
    code, out, _ = run_cmd(capsys, "run", "stop", run_id, "--yes", "--json")
    assert code == 0 and json.loads(out)["status"] == "stopped"
    assert json.loads(run_cmd(capsys, "run", "status", run_id, "--json")[1])["status"] == "stopped"
    code, _, err = run_cmd(capsys, "run", "stop", run_id, "--yes")
    assert code == 1 and "already stopped" in err


def test_run_stop_removes_containers(capsys, demo):
    run_id = start_run(capsys, demo)
    demo["fakes"].docker.orphans = ["abc123"]
    run_cmd(capsys, "run", "stop", run_id, "--yes")
    assert demo["fakes"].docker.removed == ["abc123"]


def test_gate_list_and_answer(capsys, demo):
    run_id = start_run(capsys, demo)
    run_dir = paths.runs("demo") / run_id
    gate = gates.open_gate(run_dir, kind="plan", title="Look at the plan", why="because")
    code, out, _ = run_cmd(capsys, "gate", "list")
    assert code == 0 and gate["id"] in out
    assert json.loads(run_cmd(capsys, "gate", "list", "demo", "--json")[1])[0]["id"] == gate["id"]
    code, _, err = run_cmd(capsys, "gate", "answer", gate["id"], "back")
    assert code == 1 and "note" in err
    code, out, _ = run_cmd(capsys, "gate", "answer", gate["id"], "approve", "--note", "ok", "--json")
    assert code == 0 and json.loads(out)["action"] == "approve"
    answer = json.loads((run_dir / "gates" / f"{gate['id']}.answer.json").read_text())
    assert answer["action"] == "approve" and answer["note"] == "ok"
    assert "Nothing is waiting" in run_cmd(capsys, "gate", "list")[1]
    assert run_cmd(capsys, "gate", "answer", "nope.1", "approve")[0] == 1
    assert run_cmd(capsys, "gate", "answer", gate["id"], "dance")[0] == 2


def test_settings_commands(capsys, demo):
    for sub in ("show", "explain", "check"):
        code, out, err = run_cmd(capsys, "settings", sub, "demo")
        assert code == 0 and "Traceback" not in out + err, sub
        code, out, _ = run_cmd(capsys, "settings", sub, "demo", "--json")
        json.loads(out)
    code, _, _ = run_cmd(capsys, "settings", "set", "demo", "max_tries=5")
    assert code == 0
    assert "max_tries = 5" in (demo["folder"] / "phoenix.toml").read_text()
    changelog = (demo["folder"] / "notes" / "changelog.md").read_text()
    assert " · cli · set max_tries to 5" in changelog
    code, _, err = run_cmd(capsys, "settings", "set", "demo", "bogus=1")
    assert code == 1 and "bogus" in err
    assert run_cmd(capsys, "settings", "set", "demo", "novalue")[0] == 2
    code, out, _ = run_cmd(capsys, "settings", "preset", "demo", "full", "--json")
    assert code == 0 and json.loads(out)["preset"] == "full"
    assert 'preset = "full"' in (demo["folder"] / "phoenix.toml").read_text()


def test_settings_check_reports_problems(capsys, demo):
    (demo["folder"] / "phoenix.toml").write_text("nonsense = 1\n")
    code, out, _ = run_cmd(capsys, "settings", "check", "demo")
    assert code == 1 and "nonsense" in out


def test_library_and_project_commands(capsys, demo):
    for argv in (("steps", "list"), ("profiles", "list"), ("presets", "list"), ("project", "list"),
                 ("project", "show", "demo"), ("doctor",)):
        code, out, err = run_cmd(capsys, *argv)
        assert code == 0 and "Traceback" not in out + err, argv
        code, out, _ = run_cmd(capsys, *argv, "--json")
        json.loads(out)
    assert "builder" in run_cmd(capsys, "steps", "list")[1]
    shown = json.loads(run_cmd(capsys, "project", "show", "demo", "--json")[1])
    assert shown["description"] == "A small demo project. Second line."
    assert shown["has_phoenix_toml"] is True
    assert shown["name"] == "demo"


def test_project_repo_from_project_json(capsys, demo):
    (demo["folder"] / ".phoenix").mkdir()
    (demo["folder"] / ".phoenix" / "project.json").write_text('{"repo": "owner/demo"}')
    assert json.loads(run_cmd(capsys, "project", "show", "demo", "--json")[1])["repo"] == "owner/demo"


def test_who_is_recorded(capsys, demo):
    run_cmd(capsys, "settings", "set", "demo", "max_tries=4", "--who", "chat:abc")
    run_cmd(capsys, "--who", "chat:def", "settings", "preset", "demo", "simple")
    lines = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert [(x["who"], x["project"]) for x in lines] == [("chat:abc", "demo"), ("chat:def", "demo")]
    events = [json.loads(x) for x in paths.events().read_text().splitlines()]
    assert any(e["type"] == "command" and e["data"]["who"] == "chat:abc" for e in events)
    assert " · chat:abc · " in (demo["folder"] / "notes" / "changelog.md").read_text()


def test_who_defaults_to_env(capsys, demo, monkeypatch):
    monkeypatch.setenv("PHOENIX_WHO", "dashboard")
    run_cmd(capsys, "settings", "set", "demo", "max_tries=4")
    assert json.loads((paths.logs() / "commands.jsonl").read_text().splitlines()[0])["who"] == "dashboard"


def test_unknown_project_and_run(capsys, demo):
    for argv in (("project", "show", "ghost"), ("settings", "show", "ghost"), ("run", "list", "ghost"),
                 ("run", "status", "no-such-run"), ("run", "log", "no-such-run"),
                 ("run", "start", "ghost", "--spec", demo["spec"])):
        code, out, err = run_cmd(capsys, *argv)
        assert code == 1 and "Traceback" not in out + err and err.strip(), argv
    code, out, _ = run_cmd(capsys, "project", "show", "ghost", "--json")
    assert code == 1 and json.loads(out)["ok"] is False


def test_usage_errors_exit_2(capsys):
    assert run_cmd(capsys, "run", "start")[0] == 2
    assert run_cmd(capsys, "nonsense")[0] == 2
