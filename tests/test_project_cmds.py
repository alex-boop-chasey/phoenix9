"""phoenix project list / show / edit / open / close / set-chat."""
import json
import time

import pytest

from phoenix9 import addresses, atomic, gates, paths, project, runs, settings, state
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


def off_until_started(host):
    """Make `systemctl is-active` say off until `start` has been called."""
    real = host.systemctl

    def systemctl(*args):
        if args[:1] == ("is-active",):
            return (0, "", "") if any(c[:2] == ["systemctl", "start"] for c in host.calls) else (3, "", "")
        return real(*args)
    host.systemctl = systemctl


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
    for key in ("name", "description", "path", "repo", "repo_owner", "repo_name", "profile", "services", "size", "chat",
                "vscode_url", "state", "chats", "last_used", "harness"):
        assert key in row
    assert row["vscode_url"] is None and row["vscode"]["reason"] == "Set the VS Code address in Global settings."
    addresses.save({"vscode_url": "https://code.example.test/"})
    row = json.loads(run_cmd(capsys, "project", "list", "--json")[1])[0]
    assert row["vscode_url"] == f"https://code.example.test/?folder={env['projects'] / 'alpha'}"


def test_list_plain_table(env, capsys):
    make(env, "alpha")
    code, out, _ = run_cmd(capsys, "project", "list")
    assert code == 0 and "harness" in out and "alpha" in out


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


def test_chat_link_prefers_session_url(env):
    make(env, "alpha", meta={"chat_session_url": "https://claude.ai/code/abc", "environment_id": "env_x"})
    assert project.chat_link("alpha", env["fakes"]) == {"state": "on", "kind": "session", "url": "https://claude.ai/code/abc"}


def test_chat_link_parses_environment_from_journalctl(env):
    folder = make(env, "alpha", meta={})
    env["host"].script(["journalctl", "-u", "claude-rc@alpha.service"],
                       out="https://claude.ai/code?environment=env_NEW2 y\nx https://claude.ai/code?environment=env_OLD1\n")
    link = project.chat_link("alpha", env["fakes"])
    assert link == {"state": "on", "kind": "environment", "url": "https://claude.ai/code?environment=env_NEW2"}
    assert json.loads((folder / ".phoenix/project.json").read_text())["environment_id"] == "env_NEW2"
    assert any("-o" in c and "cat" in c for c in env["host"].calls if c[0] == "journalctl")


def test_chat_link_none(env):
    make(env, "alpha")
    assert project.chat_link("alpha", env["fakes"]) == {"state": "on", "kind": "none", "url": None}


def new_run(env, name, status, tasks):
    run_dir = runs.run_dir(name, "r1")
    st = state.new_state("r1", name, {str(i + 1): {**state.new_task("t"), "status": s} for i, s in enumerate(tasks)})
    st["status"] = status
    atomic.write_json(run_dir / "state.json", st)
    return run_dir


def test_harness_status_idle_running_needs_you_queued(env):
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


def test_chats_counted_from_cgroup_procs(env):
    host = env["host"]
    host.script(["systemctl", "show", "-p", "ControlGroup"], out="/system.slice/claude-rc@alpha.service\n")
    host.files["/sys/fs/cgroup/system.slice/claude-rc@alpha.service/cgroup.procs"] = "10\n11\n12\n"
    host.files["/proc/10/cmdline"] = "claude\0--sdk-url\0wss://x\0"
    host.files["/proc/11/cmdline"] = "node\0server.js\0"
    host.files["/proc/12/cmdline"] = "claude\0--sdk-url\0wss://y\0"
    assert project.chats_open(host, "alpha") == 2
    host.script(["systemctl", "show", "-p", "ControlGroup"], out="\n")
    assert project.chats_open(host, "alpha") == 0


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


def test_open_runs_enable_trust_start(env):
    folder = make(env, "alpha")
    off_until_started(env["host"])
    r = project.open_project("alpha", env["fakes"], "alex")
    assert r["already"] is False
    verbs = [c[1] for c in env["host"].calls if c[0] == "systemctl"]
    assert verbs[:2] == ["enable", "start"]
    assert json.loads(env["host"].files[str(env["home"].parent / "claude.json")])["projects"][str(folder)][
        "hasTrustDialogAccepted"] is True
    assert (folder / ".phoenix/last-used").exists()


def test_open_reports_not_trusted_error(env):
    make(env, "alpha")
    off_until_started(env["host"])
    env["host"].script(["journalctl"], out="boot\nfolder is not trusted\n")
    with pytest.raises(OpsError, match="failed to start: folder is not trusted"):
        project.open_project("alpha", env["fakes"], "alex")
    assert ["systemctl", "stop", "claude-rc@alpha.service"] in env["host"].calls


def test_close_refuses_home_and_open_chats(env):
    make(env, "home")
    make(env, "alpha")
    with pytest.raises(OpsError, match="front door"):
        project.close_project("home", env["fakes"], "alex")
    env["host"].script(["systemctl", "show"], out="/g\n")
    env["host"].files["/sys/fs/cgroup/g/cgroup.procs"] = "5\n"
    env["host"].files["/proc/5/cmdline"] = "claude\0--sdk-url\0x"
    with pytest.raises(OpsError, match="1 chat"):
        project.close_project("alpha", env["fakes"], "alex")
    project.close_project("alpha", env["fakes"], "alex", force=True)
    assert ["systemctl", "disable", "-q", "--now", "claude-rc@alpha.service"] in env["host"].calls


def test_close_needs_yes(env, capsys):
    make(env, "alpha")
    code, _, err = run_cmd(capsys, "project", "close", "alpha")
    assert code != 0 and "--yes" in err
    assert not any(c[:2] == ["systemctl", "disable"] for c in env["host"].calls)
    assert run_cmd(capsys, "project", "close", "alpha", "--yes")[0] == 0


def test_set_chat_validates_url(env):
    folder = make(env, "alpha")
    for bad in ("https://claude.ai/code?environment=env_1", "http://claude.ai/code/abc", "https://evil.com/code/abc",
                "https://claude.ai/code/abc/def"):
        with pytest.raises(OpsError):
            project.set_chat("alpha", bad, "alex")
    project.set_chat("alpha", "https://claude.ai/code/session_01-A", "alex")
    assert json.loads((folder / ".phoenix/project.json").read_text())["chat_session_url"].endswith("session_01-A")


@pytest.mark.parametrize("argv", [
    ["edit", "alpha", "--description", "New words."],
    ["open", "alpha"],
    ["close", "alpha", "--yes"],
    ["set-chat", "alpha", "https://claude.ai/code/abc"],
])
def test_changing_commands_write_command_event(env, capsys, argv):
    make(env, "alpha")
    if argv[0] == "open":
        off_until_started(env["host"])
    code, _, err = run_cmd(capsys, "project", *argv, "--who", "chat:abc")
    assert code == 0, err
    events = [json.loads(x) for x in paths.events().read_text().splitlines()]
    cmds = [e for e in events if e["type"] == "command"]
    assert cmds and cmds[-1]["data"]["who"] == "chat:abc" and cmds[-1]["project"] == "alpha"
    assert cmds[-1]["data"]["command"].startswith(f"project {argv[0]} alpha")


def test_show_json_has_changelog_and_gates(env, capsys):
    make(env, "alpha")
    project.set_chat("alpha", "https://claude.ai/code/abc", "alex")
    code, out, _ = run_cmd(capsys, "project", "show", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["changelog"] and data["gates"] == [] and data["chat"]["kind"] == "session"


# ----------------------------------------------------------------------------- chat and VS Code links (always work)
def meta_of(folder):
    return json.loads((folder / ".phoenix/project.json").read_text())


def journal_calls(host):
    return [c for c in host.calls if c[0] == "journalctl"]


def test_chat_link_reads_journal_since_unit_start_not_fixed_lines(env):
    folder = make(env, "alpha", meta={})
    env["host"].script(["systemctl", "show", "-p", "ActiveEnterTimestamp"], out="Mon 2026-11-02 10:00:00 UTC\n")
    env["host"].script(["journalctl"], out="noise\nhttps://claude.ai/code?environment=env_A1\n")
    link = project.chat_link("alpha", env["fakes"])
    call = journal_calls(env["host"])[0]
    assert "--since" in call and "Mon 2026-11-02 10:00:00 UTC" in call and "-n" not in call
    assert link["url"].endswith("env_A1")
    meta = meta_of(folder)
    assert meta["chat_env_id"] == "env_A1" and meta["chat_env_seen"].endswith("Z")


def test_chat_link_rotated_logs_found_once_then_kept(env):
    """The id was read once; a later empty (rotated) journal does not lose it."""
    folder = make(env, "alpha", meta={})
    env["host"].script(["systemctl", "show"], out="T1\n")
    env["host"].script_seq(["journalctl"], [(0, "https://claude.ai/code?environment=env_A1\n", ""), (0, "", "")])
    assert project.chat_link("alpha", env["fakes"])["url"].endswith("env_A1")
    assert project.chat_link("alpha", env["fakes"])["url"].endswith("env_A1")
    assert len(journal_calls(env["host"])) == 1       # same start time: the stored id is used
    assert meta_of(folder)["chat_env_id"] == "env_A1"


def test_chat_link_restart_replaces_old_id(env):
    folder = make(env, "alpha", meta={})
    env["host"].script_seq(["systemctl", "show"], [(0, "T1\n", ""), (0, "T2\n", "")])
    env["host"].script_seq(["journalctl"], [(0, "https://claude.ai/code?environment=env_OLD\n", ""),
                                             (0, "https://claude.ai/code?environment=env_NEW\n", "")])
    assert project.chat_link("alpha", env["fakes"])["url"].endswith("env_OLD")
    assert project.chat_link("alpha", env["fakes"])["url"].endswith("env_NEW")
    assert meta_of(folder)["environment_id"] == "env_NEW"


def test_chat_link_no_link_yet_keeps_asking(env):
    folder = make(env, "alpha", meta={})
    env["host"].script(["systemctl", "show"], out="T1\n")
    env["host"].script(["journalctl"], out="starting...\n")
    assert project.chat_link("alpha", env["fakes"]) == {"state": "on", "kind": "none", "url": None}
    assert "chat_env_id" not in meta_of(folder)
    project.chat_link("alpha", env["fakes"])
    assert len(journal_calls(env["host"])) == 2


def test_chat_off_has_no_url_even_with_stored_id(env):
    make(env, "alpha", meta={"environment_id": "env_X", "chat_session_url": "https://claude.ai/code/abc"})
    env["host"].script(["systemctl", "is-active"], rc=3)
    assert project.chat_link("alpha", env["fakes"]) == {"state": "off", "kind": "none", "url": None}
    assert journal_calls(env["host"]) == []


def test_vscode_link_needs_folder(env):
    make(env, "alpha")
    addresses.save({"vscode_url": "https://code.example.test"})
    assert project.vscode_link("alpha") == {"url": f"https://code.example.test/?folder={env['projects'] / 'alpha'}",
                                            "reason": None}
    gone = project.vscode_link("ghost")
    assert gone["url"] is None and "does not exist" in gone["reason"]
    assert project.info("alpha", env["fakes"])["vscode"]["reason"] is None


def test_chat_start_switches_on_and_returns_chat(env):
    folder = make(env, "alpha", meta={})
    off_until_started(env["host"])
    env["host"].script(["journalctl"], out="https://claude.ai/code?environment=env_S1\n")
    from phoenix9.ops import projects as ops_projects
    out = ops_projects.chat_start("alpha", "test")
    assert out["chat"]["url"].endswith("env_S1") and out["already"] is False
    assert ["systemctl", "start", "claude-rc@alpha.service"] in env["host"].calls
    assert meta_of(folder)["environment_id"] == "env_S1"


def test_journal_search_stops_at_first_match(env):
    env["host"].script(["journalctl"], out="a\nhttps://claude.ai/code?environment=env_A1\n" + "more\n" * 1000)
    assert project._env_id_in_journal(env["host"], "alpha", "") == "env_A1"
    assert env["host"].lines_read == 2
    assert "-r" in journal_calls(env["host"])[0]


def test_real_first_match_stops_a_endless_command():
    import re
    import sys
    from phoenix9.adapters import Host
    code = "import sys\nprint('hi')\nprint('id=X1')\nwhile True: print('x')"
    assert Host().first_match([sys.executable, "-c", code], re.compile(r"id=\w+"), timeout=20) == "id=X1"


def test_list_does_not_search_the_journal_in_the_request(env):
    import threading
    folder = make(env, "alpha", meta={})
    gate, started = threading.Event(), threading.Event()
    host = env["host"]
    real = host.first_match

    def blocked(argv, pattern, timeout=120):
        started.set()
        gate.wait(10)
        return real(argv, pattern, timeout)
    host.first_match = blocked
    host.script(["journalctl"], out="https://claude.ai/code?environment=env_Z9\n")
    try:
        rows = project.list_projects(env["fakes"], wait=0.05)
        assert rows[0]["chat"] == {"state": "on", "kind": "none", "url": None}
        assert started.wait(5)
    finally:
        gate.set()
    for _ in range(100):
        if meta_of(folder).get("environment_id"):
            break
        time.sleep(0.05)
    assert project.list_projects(env["fakes"], wait=0.05)[0]["chat"]["url"].endswith("env_Z9")


def test_list_skips_journal_when_chat_is_off(env):
    make(env, "alpha", meta={})
    env["host"].script(["systemctl", "is-active"], rc=3)
    project.list_projects(env["fakes"])
    assert journal_calls(env["host"]) == []
