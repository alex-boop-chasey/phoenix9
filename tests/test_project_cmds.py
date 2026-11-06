"""phoenix project list / show / edit (the per-project chat commands are gone)."""
import json

import pytest

from phoenix9 import atomic, gates, paths, project, runs, settings, state
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


@pytest.fixture
def env(phoenix_env, tmp_path, monkeypatch):
    """Fake adapters injected into ops, and a temp .claude.json."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    claude = tmp_path / "claude.json"
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude))
    fakes.host.files[str(claude)] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    return {"fakes": fakes, "host": fakes.host, "clock": fakes.clock, "projects": phoenix_env["projects"],
            "home": phoenix_env["home"]}


def make(env, name="demo", text=None, meta=None):
    folder = env["projects"] / name
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text(text or f"# {name}\n\nAbout {name}.\n\n- Profile: python-script\n- Repo: (none yet)\n")
    if meta is not None:
        atomic.write_json(folder / ".phoenix" / "project.json", meta)
    return folder


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_list_finds_projects_with_claude_md_only(env):
    make(env, "alpha")
    (env["projects"] / "no-notes").mkdir()
    (env["projects"] / ".proj").mkdir()
    assert [p["name"] for p in project.list_projects(env["fakes"])] == ["alpha"]


def test_list_json_fields(env, capsys):
    make(env, "alpha")
    code, out, _ = run_cmd(capsys, "project", "list", "--json")
    assert code == 0
    row = json.loads(out)[0]
    for key in ("name", "description", "path", "repo", "repo_owner", "repo_name", "profile", "services", "size",
                "vscode_url", "last_used", "harness"):
        assert key in row
    for gone in ("chat", "chat_url", "chats", "state"):
        assert gone not in row
    assert row["vscode_url"] == f"https://files.rebirthwebdesign.com.au/?folder={env['projects'] / 'alpha'}"


def test_list_plain_table(env, capsys):
    make(env, "alpha")
    code, out, _ = run_cmd(capsys, "project", "list")
    assert code == 0 and "harness" in out and "alpha" in out
    assert "chats" not in out.splitlines()[0]


def test_description_from_claude_md(env):
    folder = make(env, "alpha", "# Alpha\n\nFirst line.\nSecond line.\n\nOther.\n")
    assert project.description(folder) == "First line. Second line."


def test_repo_from_origin_when_not_recorded(env, monkeypatch):
    folder = make(env, "alpha")
    (folder / "code").mkdir()
    monkeypatch.setattr(project.git, "remote_url", lambda code: "git@github.com:me/alpha.git")
    assert project.repo_of(folder) == "git@github.com:me/alpha.git"
    assert project.split_repo(project.repo_of(folder)) == {"owner": "me", "name": "alpha"}
    atomic.write_json(folder / ".phoenix" / "project.json", {"repo": "you/other"})
    assert project.repo_of(folder) == "you/other"
    assert project.split_repo("you/other") == {"owner": "you", "name": "other"}


def test_size_uses_cache_then_refreshes(env):
    make(env, "alpha")
    path = str(env["projects"] / "alpha")
    env["host"].sizes[path] = 100
    assert project.size("alpha", env["fakes"]) == 100
    env["host"].sizes[path] = 200
    env["clock"].t += 200
    assert project.size("alpha", env["fakes"]) == 100
    env["clock"].t += 200
    assert project.size("alpha", env["fakes"]) == 200
    assert json.loads((paths.cache() / "sizes.json").read_text())["alpha"]["bytes"] == 200


def test_list_shows_dots_until_measured(env):
    make(env, "alpha")
    env["host"].sizes[str(env["projects"] / "alpha")] = 5
    assert project.info("alpha", env["fakes"], size_wait=False)["size"] is None
    assert project.list_projects(env["fakes"])[0]["size"] == 5


def new_run(env, name, status, tasks):
    run_dir = runs.run_dir(name, "r1")
    st = state.new_state("r1", name, {str(i + 1): {**state.new_task("t"), "status": s} for i, s in enumerate(tasks)})
    st["status"] = status
    atomic.write_json(run_dir / "state.json", st)
    return run_dir


def test_harness_status_idle_running_needs_you_queued(env):
    import time
    from phoenix9 import heartbeat
    heartbeat.write(time.time())          # the runner is alive (A6: no heartbeat = worker not responding)
    make(env, "alpha")
    assert project.harness_status("alpha") == "idle"
    run_dir = new_run(env, "alpha", "queued", ["pending"] * 3)
    assert project.harness_status("alpha") == "queued"
    new_run(env, "alpha", "running", ["passed", "passed", "running", "pending"])
    assert project.harness_status("alpha") == "running task 3 of 4"
    gates.open_gate(run_dir, kind="plan", title="Approve", why="because")
    assert project.harness_status("alpha") == "needs you"
    new_run(env, "beta", "done", ["passed"])
    assert project.harness_status("beta") == "idle"


def test_edit_description_keeps_rest_of_claude_md(env):
    folder = make(env, "alpha")
    project.edit("alpha", env["fakes"], "alex", description_text="A brand new description.")
    text = (folder / "CLAUDE.md").read_text()
    assert text == "# alpha\n\nA brand new description.\n\n- Profile: python-script\n- Repo: (none yet)\n"
    assert "· alex · changed description" in (folder / "notes/changelog.md").read_text()


def test_edit_profile_validated(env):
    folder = make(env, "alpha")
    with pytest.raises(OpsError, match="Unknown profile"):
        project.edit("alpha", env["fakes"], "alex", profile="nope")
    assert not (folder / "phoenix.toml").exists()
    project.edit("alpha", env["fakes"], "alex", profile="python-script")
    assert settings.load_project(folder)["profile"] == "python-script"


def test_edit_repo_checks_github_and_sets_origin(env):
    folder = make(env, "alpha")
    (folder / "code").mkdir()
    env["host"].script(["gh", "repo", "view"], rc=1, err="not found")
    with pytest.raises(OpsError, match="Cannot see"):
        project.edit("alpha", env["fakes"], "alex", repo="me/alpha")
    env["host"].script(["gh", "repo", "view"])
    env["host"].script(["git", "-c"], rc=0)
    project.edit("alpha", env["fakes"], "alex", repo="me/alpha")
    assert any(c[-3:] == ["set-url", "origin", "https://github.com/me/alpha.git"] for c in env["host"].calls)
    assert json.loads((folder / ".phoenix/project.json").read_text())["repo"] == "me/alpha"


@pytest.mark.parametrize("argv", [
    ["edit", "alpha", "--description", "New words."],
])
def test_changing_commands_write_command_event(env, capsys, argv):
    make(env, "alpha")
    code, _, err = run_cmd(capsys, "project", *argv, "--who", "chat:abc")
    assert code == 0, err
    events = [json.loads(x) for x in paths.events().read_text().splitlines()]
    cmds = [e for e in events if e["type"] == "command"]
    assert cmds and cmds[-1]["data"]["who"] == "chat:abc" and cmds[-1]["project"] == "alpha"
    assert cmds[-1]["data"]["command"].startswith(f"project {argv[0]} alpha")


def test_show_json_has_changelog_and_gates(env, capsys):
    make(env, "alpha")
    project.edit("alpha", env["fakes"], "alex", description_text="Fresh words.")
    code, out, _ = run_cmd(capsys, "project", "show", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["changelog"] and data["gates"] == [] and "chat" not in data


def test_show_plain_has_no_chat_lines(env, capsys):
    make(env, "alpha")
    code, out, _ = run_cmd(capsys, "project", "show", "alpha")
    assert code == 0 and "chat server" not in out and "chat link" not in out and "last used:" in out


@pytest.mark.parametrize("verb", ["open", "close", "set-chat"])
def test_chat_commands_are_gone(env, capsys, verb):
    make(env, "alpha")
    code, _, err = run_cmd(capsys, "project", verb, "alpha")
    assert code == 2 and "invalid choice" in err
    for name in ("open_project", "close_project", "set_chat", "chat_link", "chat_start", "chats_open", "is_on", "unit"):
        assert not hasattr(project, name)


def test_listing_never_asks_systemd_or_the_journal(env):
    make(env, "alpha", meta={"chat_session_url": "https://claude.ai/code/abc", "environment_id": "env_x"})
    row = project.list_projects(env["fakes"])[0]
    assert "chat" not in row and not any(c[0] in ("systemctl", "journalctl") for c in env["host"].calls)


# ----------------------------------------------------------------------------- VS Code link (always works)
def test_vscode_link_needs_folder(env):
    make(env, "alpha")
    assert project.vscode_link("alpha") == {"url": f"https://files.rebirthwebdesign.com.au/?folder={env['projects'] / 'alpha'}",
                                            "reason": None}
    gone = project.vscode_link("ghost")
    assert gone["url"] is None and "does not exist" in gone["reason"]
    assert project.info("alpha", env["fakes"])["vscode"]["reason"] is None


