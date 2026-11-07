"""Delete project, dry run: the plan lists everything that would go and the refusals; nothing is touched."""
import datetime
import json
import subprocess

import pytest

from phoenix9 import atomic, deploy, keys, paths, project_delete
from phoenix9.ops.common import NotFound
from test_project_cmds import env, make  # noqa: F401  (fixtures)

PR_JSON = json.dumps([{"number": 7, "title": "Add x", "url": "https://github.com/me/alpha/pull/7"}])


def git_repo(code, remote=None, origin_url=None, commit=True):
    """A real tiny repo in `code` with one commit (and an optional origin that has it, or just an origin URL)."""
    code.mkdir(parents=True, exist_ok=True)
    run = lambda *a, cwd=code: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    (code / "a.txt").write_text("a")
    if commit:
        run("add", ".")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    if remote:
        run("clone", "-q", "--bare", str(code), str(remote), cwd=code.parent)
        run("remote", "add", "origin", str(remote))
        run("fetch", "-q", "origin")
    if origin_url:
        run("remote", "add", "origin", origin_url)


def host_git(host, folder):
    """Make the fake host really run git commands."""
    def run(argv, timeout=60, cwd=None):
        host.calls.append(list(argv))
        if "fetch" in argv:                     # never reach the network from a test
            return 1, "", "fetch is off in tests"
        p = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    real = host.run
    host.run = lambda argv, timeout=60, cwd=None: run(argv, timeout, cwd) if argv[0] == "git" else real(argv, timeout, cwd)


def make_run(name, run_id, status):
    d = paths.runs(name) / run_id
    st = {"run_id": run_id, "project": name, "status": status, "created": "2026-11-07T10:00:00Z",
          "updated": "2026-11-07T10:00:00Z", "tasks": {}}
    atomic.write_json(d / "state.json", st)


def test_plan_basic_fields(env, tmp_path):
    folder = make(env, "alpha", meta={"repo": "me/alpha"})
    env["host"].sizes[str(folder)] = 1234
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["name"] == "alpha" and plan["folder"] == str(folder)
    assert plan["size"] == env["host"].du_bytes(folder)
    assert plan["repo"] == "me/alpha" and plan["refusals"] == []


def test_plan_without_repo(env):
    make(env, "alpha")
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["repo"] is None and plan["open_prs"] == []


def test_unknown_project(env):
    with pytest.raises(NotFound):
        project_delete.plan("nope", "cli", env["fakes"])


def test_open_prs(env):
    make(env, "alpha", meta={"repo": "me/alpha"})
    env["host"].script(["gh", "pr", "list"], out=PR_JSON)
    plan = project_delete.plan("alpha", "dashboard", env["fakes"])
    assert plan["open_prs"] == [{"number": 7, "title": "Add x", "url": "https://github.com/me/alpha/pull/7"}]
    call = next(c for c in env["host"].calls if c[:3] == ["gh", "pr", "list"])
    assert "--state" in call and "open" in call and "--json" in call


def test_open_prs_gh_fails_gives_note(env):
    make(env, "alpha", meta={"repo": "me/alpha"})
    env["host"].script(["gh", "pr", "list"], rc=1, err="not logged in")
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["open_prs"] == [] and "not logged in" in plan["open_prs_note"]


def test_unpushed_without_remote_counts_all(env):
    folder = make(env, "alpha")
    git_repo(folder / "code")
    host_git(env["host"], folder)
    assert project_delete.plan("alpha", "cli", env["fakes"])["unpushed"] == 1


def test_unpushed_with_remote_and_safe_flags(env, tmp_path):
    folder = make(env, "alpha")
    git_repo(folder / "code", tmp_path / "origin.git")
    host_git(env["host"], folder)
    assert project_delete.plan("alpha", "cli", env["fakes"])["unpushed"] == 0
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "two"],
                   cwd=folder / "code", check=True, capture_output=True)
    assert project_delete.plan("alpha", "cli", env["fakes"])["unpushed"] == 1
    gits = [c for c in env["host"].calls if c[0] == "git"]
    assert gits and all("core.fsmonitor=false" in c and "core.hooksPath=/dev/null" in c for c in gits)


def test_runs(env):
    make(env, "alpha")
    make_run("alpha", "r1", "done")
    make_run("alpha", "r2", "failed")
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["runs"]["count"] == 2 and set(plan["runs"]["newest"]) == {"r1", "r2"}


def test_keys_names_only_no_values(env):
    make(env, "alpha")
    keys.set_key("alpha", "API_TOKEN", "sekret-value-123")
    keys.set_key("alpha", "PLAIN", "plain-value-456", secret=False)
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["keys"] == ["API_TOKEN", "PLAIN"]
    text = json.dumps(plan)
    assert "sekret-value-123" not in text and "plain-value-456" not in text


def test_chat_unit_and_state(env):
    make(env, "alpha")
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["chat"]["unit"] == "claude-rc-chat@alpha" and plan["chat"]["state"]


def test_deployments_from_settings_and_records(env):
    folder = make(env, "alpha")
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "vps-docker"\n[deploy.settings]\nurl = "https://alpha.example.test"\n')
    atomic.write_text(deploy.records_path("alpha"),
                      json.dumps({"ok": True, "kind": "deploy", "deployer": "vps-docker",
                                  "url": "https://live.example.test"}) + "\n")
    dep = project_delete.plan("alpha", "cli", env["fakes"])["deployments"]
    assert len(dep) == 1 and dep[0]["target"] == "vps-docker"
    assert "https://alpha.example.test" in dep[0]["links"] and "https://live.example.test" in dep[0]["links"]
    assert "still live, take it down yourself" in dep[0]["note"]


def test_no_deployments_when_none(env):
    make(env, "alpha")
    assert project_delete.plan("alpha", "cli", env["fakes"])["deployments"] == []


@pytest.mark.parametrize("name", ["phoenix9", "home"])
def test_refuses_protected(env, name):
    make(env, name)
    refusals = project_delete.plan(name, "cli", env["fakes"])["refusals"]
    assert len(refusals) == 1 and name in refusals[0]


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "paused-limit"])
def test_refuses_active_build(env, status):
    make(env, "alpha")
    make_run("alpha", "r1", status)
    refusals = project_delete.plan("alpha", "cli", env["fakes"])["refusals"]
    assert len(refusals) == 1 and status in refusals[0]


def test_finished_build_does_not_refuse(env):
    make(env, "alpha")
    make_run("alpha", "r1", "done")
    assert project_delete.plan("alpha", "cli", env["fakes"])["refusals"] == []


def test_refuses_working_chat(env, monkeypatch):
    make(env, "alpha")
    monkeypatch.setattr(project_delete.projectchat, "state", lambda n, a: {"state": "working"})
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["chat"]["state"] == "working" and "chat is working" in plan["refusals"][0]


@pytest.mark.parametrize("who", ["agent", "phoenix-agent", "chat:alpha", "chat:home", "runner", ""])
def test_refuses_other_callers(env, who):
    make(env, "alpha")
    refusals = project_delete.plan("alpha", who, env["fakes"])["refusals"]
    assert len(refusals) == 1 and "Only Alex" in refusals[0]


def test_deleted_projects_path(monkeypatch, tmp_path):
    monkeypatch.delenv("PHOENIX_DELETED", raising=False)
    assert str(paths.deleted_projects()) == "/root/deleted-projects"
    monkeypatch.setenv("PHOENIX_DELETED", str(tmp_path / "d"))
    assert paths.deleted_projects() == tmp_path / "d"


def test_cli_dry_run_text_and_json(env, capsys):
    from test_project_cmds import run_cmd
    make(env, "alpha", meta={"repo": "me/alpha"})
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--dry-run")
    assert code == 0 and "Deleting alpha would remove" in out and "me/alpha" in out
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--dry-run", "--json")
    assert code == 0 and json.loads(out)["name"] == "alpha"


def test_cli_delete_needs_dry_run(env, capsys):
    from test_project_cmds import run_cmd
    make(env, "alpha")
    assert run_cmd(capsys, "project", "delete", "alpha")[0] == 1


def test_ops_delete_plan_uses_given_caller(env):
    from phoenix9.ops import projects
    make(env, "alpha")
    assert projects.delete_plan("alpha", "agent")["refusals"]
    assert projects.delete_plan("alpha", "dashboard")["refusals"] == []


# ---- safety copy ----

from phoenix9.ops.common import OpsError  # noqa: E402


def _project_with_stuff(env, name="alpha"):
    """A project with a real repo, an untracked file, caches, notes, a run and a work folder."""
    folder = make(env, name, meta={"repo": "me/alpha", "source": "empty"})
    git_repo(folder / "code", origin_url="https://github.com/me/alpha.git")
    host_git(env["host"], folder)
    code = folder / "code"
    (code / "local.txt").write_text("untracked")
    (code / "node_modules" / "x").mkdir(parents=True)
    (code / "node_modules" / "x" / "i.js").write_text("x")
    (code / "src" / "__pycache__").mkdir(parents=True)
    (code / "src" / "__pycache__" / "m.pyc").write_text("x")
    (code / "dist").mkdir()
    (code / "dist" / "o.js").write_text("x")
    (folder / "notes" / "n.md").write_text("note")
    make_run(name, "r1", "passed")
    (paths.home() / "work" / name / "r1").mkdir(parents=True)
    (paths.home() / "work" / name / "r1" / "w.txt").write_text("w")
    return folder


def _names(tar_path):
    import tarfile
    with tarfile.open(tar_path) as t:
        return t.getnames()


def test_backup_makes_all_files(env, tmp_path):
    folder = _project_with_stuff(env)
    dest = project_delete.backup("alpha", "cli", env["fakes"])
    assert dest.parent == paths.deleted_projects() and dest.name.startswith("alpha-1970")
    assert (dest.stat().st_mode & 0o777) == 0o700
    assert sorted(p.name for p in dest.iterdir()) == ["RESTORE.md", "files.tar.gz", "manifest.json", "repo.bundle", "runs.tar.gz"]
    ok = subprocess.run(["git", "bundle", "verify", str(dest / "repo.bundle")], cwd=folder / "code",
                        capture_output=True)
    assert ok.returncode == 0
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(dest / "repo.bundle"), str(clone)], check=True, capture_output=True)
    assert (clone / "a.txt").read_text() == "a"
    assert "git" in (dest / "RESTORE.md").read_text()
    for call in env["host"].calls:
        if call[0] == "git":
            assert call[1:5] == ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]


def test_backup_files_untracked_in_caches_out(env):
    _project_with_stuff(env)
    dest = project_delete.backup("alpha", "cli", env["fakes"])
    names = _names(dest / "files.tar.gz")
    assert "notes/n.md" in names and "code/local.txt" in names and "CLAUDE.md" in names
    assert "code/a.txt" in names and "code/dist/o.js" in names   # the whole working copy, build output too
    assert not [n for n in names if "node_modules" in n or "__pycache__" in n or n.startswith("code/.git")]


def test_backup_keeps_unsaved_edits_and_nested_repos(env):
    folder = _project_with_stuff(env)
    code = folder / "code"
    (code / "a.txt").write_text("edited, never committed")
    (code / "staged.txt").write_text("staged")
    subprocess.run(["git", "add", "staged.txt"], cwd=code, check=True)
    git_repo(code / "vendor" / "lib")                  # a nested repo with its own history
    (code / ".next" / "cache").mkdir(parents=True)
    (code / ".next" / "cache" / "c.bin").write_text("x")
    (code / ".next" / "server.js").write_text("x")
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["unsaved_edits"] == 8   # a.txt, staged.txt, vendor/, .next/ + local.txt, dist/, src/, node_modules/
    dest = project_delete.backup("alpha", "cli", env["fakes"])
    import tarfile
    with tarfile.open(dest / "files.tar.gz") as t:
        names = t.getnames()
        assert t.extractfile("code/a.txt").read() == b"edited, never committed"
    assert "code/staged.txt" in names and "code/vendor/lib/a.txt" in names
    assert any(n.startswith("code/vendor/lib/.git/") for n in names)
    assert "code/.next/server.js" in names and not [n for n in names if ".next/cache" in n]
    assert "unsaved" in (dest / "RESTORE.md").read_text()


def test_cli_dry_run_shows_unsaved_edits(env, capsys):
    from test_project_cmds import run_cmd
    _project_with_stuff(env)
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--dry-run")
    assert code == 0 and "Unsaved edits (kept in the safety copy): 4" in out


def test_backup_runs_tar(env):
    _project_with_stuff(env)
    dest = project_delete.backup("alpha", "cli", env["fakes"])
    names = _names(dest / "runs.tar.gz")
    assert "runs/alpha/r1/state.json" in names and "work/alpha/r1/w.txt" in names


def test_backup_manifest(env):
    folder = _project_with_stuff(env)
    dest = project_delete.backup("alpha", "dashboard", env["fakes"])
    m = json.loads((dest / "manifest.json").read_text())
    assert m["name"] == "alpha" and m["folder"] == str(folder) and m["who"] == "dashboard"
    assert m["repo"] == "me/alpha" and m["repo_url"] == "me/alpha"
    assert m["when"] == "1970-01-01T00:16:40Z"
    assert "repo.bundle" in m["files"] and "manifest.json" in m["files"]
    assert m["plan"]["name"] == "alpha" and m["plan"]["runs"]["count"] == 1


def test_backup_without_git_skips_bundle(env):
    folder = make(env, "plain")
    (folder / "code").mkdir()
    (folder / "code" / "f.txt").write_text("f")
    dest = project_delete.backup("plain", "cli", env["fakes"])
    assert not (dest / "repo.bundle").exists()
    assert "code/f.txt" in _names(dest / "files.tar.gz")
    assert json.loads((dest / "manifest.json").read_text())["notes"]


def test_backup_failure_leaves_nothing(env):
    _project_with_stuff(env)
    real = env["host"].run

    def fail_verify(argv, timeout=60, cwd=None):
        if "verify" in argv:
            return 1, "", "bad bundle"
        return real(argv, timeout, cwd)
    env["host"].run = fail_verify
    with pytest.raises(OpsError, match="bundle"):
        project_delete.backup("alpha", "cli", env["fakes"])
    assert list(paths.deleted_projects().iterdir()) == []


def test_backup_unknown_project_leaves_nothing(env):
    with pytest.raises(NotFound):
        project_delete.backup("nope", "cli", env["fakes"])
    assert not paths.deleted_projects().exists() or list(paths.deleted_projects().iterdir()) == []


def _fake_copy(name, stamp):
    d = paths.deleted_projects() / f"{name}-{stamp}"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text("{}")
    return d


def test_prune_keeps_new_removes_old(env, monkeypatch):
    old, new = _fake_copy("a", "20260901-1000"), _fake_copy("b", "20261105-1000")
    other = paths.deleted_projects() / "not-a-copy"
    other.mkdir()
    now = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc).timestamp()
    assert project_delete.prune_backups(env["fakes"], now) == ["a-20260901-1000"]
    assert not old.exists() and new.exists() and other.exists()


def test_prune_uses_keep_days_setting(env):
    (env["home"] / "config").mkdir()
    (env["home"] / "config" / "global.toml").write_text("[delete]\nkeep_days = 1\n")
    new = _fake_copy("b", "20261105-1000")
    now = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc).timestamp()
    project_delete.prune_backups(env["fakes"], now)
    assert not new.exists()


def test_prune_without_folder(env):
    assert project_delete.prune_backups(env["fakes"], 1e9) == []


# ---- delete ----

from phoenix9 import events as events_mod  # noqa: E402
from phoenix9.project_removal import _save_removed  # noqa: E402

SCOPE = "The GitHub repo me/alpha was NOT deleted: Phoenix's GitHub login isn't allowed to delete repos."


@pytest.fixture
def unitdir(tmp_path, monkeypatch):
    """A fake systemd folder inside the temp area, with alpha's chat drop-in in it."""
    d = paths.home() / "systemd"
    (d / "claude-rc-chat@alpha.service.d").mkdir(parents=True)
    (d / "claude-rc-chat@alpha.service.d" / "x.conf").write_text("x")
    monkeypatch.setattr(project_delete, "SYSTEMD_DIR", d)
    return d


def _stuff(env):
    """A project with a repo, keys, a run, an INDEX line and a removed row."""
    folder = _project_with_stuff(env)
    keys.set_key("alpha", "API_TOKEN", "sekret-value-123")
    (env["projects"] / "INDEX.md").write_text("| alpha | me/alpha | (new) |\n| beta | - | (new) |\n")
    _save_removed([{"name": "alpha", "path": str(folder), "repo": "me/alpha", "removed_on": "2026-01-01"}])
    return folder


def _all_there(folder):
    assert folder.is_dir() and (paths.runs("alpha") / "r1").is_dir() and (paths.keys() / "alpha.toml").is_file()


def test_delete_order_and_everything_gone(env, unitdir):
    folder = _stuff(env)
    res = project_delete.delete("alpha", "alpha", "dashboard", env["fakes"])
    assert [s["step"] for s in res["steps"]] == ["records and runs", "chat unit", "project folder", "saved keys",
                                                 "folder trust", "removed list and INDEX.md", "GitHub repo"]
    assert all(s["ok"] for s in res["steps"]) and res["not_done"] == []
    assert not folder.exists() and not paths.runs("alpha").exists() and not (paths.keys() / "alpha.toml").exists()
    assert not (unitdir / "claude-rc-chat@alpha.service.d").exists()
    assert (env["projects"] / "INDEX.md").read_text() == "| beta | - | (new) |\n"
    from phoenix9 import project_removal
    assert project_removal.removed_list() == []
    calls = env["host"].calls
    sysc = [c[1:3] for c in calls if c[0] == "systemctl"]
    assert sysc == [["stop", "claude-rc-chat@alpha"], ["disable", "claude-rc-chat@alpha"], ["daemon-reload"]] or \
        [c[1] for c in calls if c[0] == "systemctl"][-3:] == ["stop", "disable", "daemon-reload"]
    assert ["gh", "repo", "delete", "me/alpha", "--yes"] in calls
    assert calls.index(["gh", "repo", "delete", "me/alpha", "--yes"]) > calls.index(["remove_tree", str(folder)])
    assert (project_delete.Path(res["backup"]) / "repo.bundle").is_file()


def test_delete_wrong_confirm(env, unitdir):
    folder = _stuff(env)
    with pytest.raises(OpsError, match="Type the project's name"):
        project_delete.delete("alpha", "alph", "dashboard", env["fakes"])
    _all_there(folder)
    assert not paths.deleted_projects().exists() or list(paths.deleted_projects().iterdir()) == []


@pytest.mark.parametrize("who", ["agent", "chat:delegate", "chat:alpha"])
def test_delete_refuses_callers(env, unitdir, who):
    folder = _stuff(env)
    with pytest.raises(OpsError, match="Only Alex"):
        project_delete.delete("alpha", "alpha", who, env["fakes"])
    _all_there(folder)


def test_delete_refuses_protected(env, unitdir):
    for name in ("phoenix9", "home"):
        folder = make(env, name)
        with pytest.raises(OpsError, match=name):
            project_delete.delete(name, name, "cli", env["fakes"])
        assert folder.is_dir()


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "paused-limit"])
def test_delete_refuses_active_build(env, unitdir, status):
    folder = _stuff(env)
    make_run("alpha", "r2", status)
    with pytest.raises(OpsError, match=status):
        project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    _all_there(folder)


def test_delete_refuses_working_chat(env, unitdir, monkeypatch):
    folder = _stuff(env)
    monkeypatch.setattr(project_delete.projectchat, "state", lambda n, a: {"state": "working"})
    with pytest.raises(OpsError, match="chat is working"):
        project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    _all_there(folder)


def test_delete_backup_failure_leaves_everything(env, unitdir):
    folder = _stuff(env)
    real = env["host"].run
    env["host"].run = lambda argv, timeout=60, cwd=None: (1, "", "bad") if "verify" in argv else real(argv, timeout, cwd)
    with pytest.raises(OpsError, match="bundle"):
        project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    _all_there(folder)
    assert (unitdir / "claude-rc-chat@alpha.service.d").exists()
    assert not [c for c in env["host"].calls if c[:2] == ["gh", "repo"] or c[:1] == ["systemctl"]]


def test_delete_scope_message_other_steps_done(env, unitdir):
    folder = _stuff(env)
    env["host"].script(["gh", "repo", "delete"], rc=1, err="HTTP 403: Must have admin rights; needs the delete_repo scope")
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert not folder.exists()
    assert [s["ok"] for s in res["steps"]] == [True] * 6 + [False]
    assert res["steps"][-1]["words"].startswith(SCOPE) and "gh auth refresh -h github.com -s delete_repo" in res["steps"][-1]["words"]
    assert len(res["not_done"]) == 1 and "delete_repo" in res["not_done"][0]["how"]


def test_delete_repo_retry_uses_manifest(env, unitdir):
    _stuff(env)
    env["host"].script(["gh", "repo", "delete"], rc=1, err="needs delete_repo scope")
    first = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    env["host"].script(["gh", "repo", "delete"], rc=0)
    res = project_delete.delete_repo("alpha", "dashboard", env["fakes"])
    assert res["steps"][0]["ok"] and res["not_done"] == [] and res["backup"] == first["backup"]
    assert env["host"].calls[-1] == ["gh", "repo", "delete", "me/alpha", "--yes"]
    with pytest.raises(OpsError, match="Only Alex"):
        project_delete.delete_repo("alpha", "agent", env["fakes"])
    with pytest.raises(NotFound):
        project_delete.delete_repo("ghost", "cli", env["fakes"])


def test_delete_chat_unit_failure_recorded(env, unitdir):
    folder = _stuff(env)
    env["host"].script(["systemctl", "disable"], rc=1, err="Access denied")
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    chat = res["steps"][1]
    assert chat["step"] == "chat unit" and not chat["ok"] and "Access denied" in chat["words"]
    assert not folder.exists() and any(n["what"] == "chat unit" for n in res["not_done"])


def test_delete_chat_unit_not_loaded_is_fine(env, unitdir):
    _stuff(env)
    env["host"].script(["systemctl", "stop"], rc=5, err="Unit claude-rc-chat@alpha.service not loaded.")
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert res["steps"][1]["ok"]


def test_delete_event_and_commands_log(env, unitdir):
    _stuff(env)
    project_delete.delete("alpha", "alpha", "dashboard", env["fakes"])
    found = [e for e in events_mod.read(paths.events()) if e["type"] == "project.deleted"]
    assert len(found) == 1 and found[0]["project"] == "alpha" and found[0]["data"]["who"] == "dashboard"
    lines = [json.loads(ln) for ln in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    mine = [ln for ln in lines if ln["command"].startswith("project delete alpha")]
    assert len(mine) >= 7 and all(ln["who"] == "dashboard" and ln["project"] == "alpha" for ln in mine)


# ---- CLI and API ----

from test_api_server import POST_HEADERS, api, dist  # noqa: E402,F401  (fixtures)


def test_cli_delete_needs_matching_confirm(env, capsys, unitdir):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    assert run_cmd(capsys, "project", "delete", "alpha")[0] == 1
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alph")
    assert code == 1 and "--confirm alpha" in err
    _all_there(folder)
    assert not [c for c in env["host"].calls if c[0] in ("remove_tree", "gh")]


@pytest.fixture
def at_terminal(monkeypatch):
    """Pretend Alex is at a terminal and types the name asked for at the prompt."""
    from phoenix9.cli import project as cli_project
    asked = []
    monkeypatch.setattr(cli_project, "_stdin_is_tty", lambda: True)

    def ask(prompt):
        asked.append(prompt)
        return prompt.split("Type ")[1].split(" ")[0]
    monkeypatch.setattr(cli_project, "_ask", ask)
    return asked


def test_cli_delete_text_and_json(env, capsys, unitdir, at_terminal):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")
    assert code == 0 and "Safety copy:" in out and "Done: chat unit" in out and "alpha is deleted." in out
    assert not folder.exists()


def test_cli_delete_json(env, capsys, unitdir, at_terminal):
    from test_project_cmds import run_cmd
    _stuff(env)
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha", "--json")
    assert code == 0 and [s["step"] for s in json.loads(out)["steps"]][-1] == "GitHub repo"


def test_cli_delete_scope_then_delete_repo(env, capsys, unitdir, at_terminal):
    from test_project_cmds import run_cmd
    _stuff(env)
    env["host"].script(["gh", "repo", "delete"], rc=1, err="needs delete_repo scope")
    code, out, _ = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")
    assert code == 0 and "Not done:" in out and "NOT deleted" in out
    env["host"].script(["gh", "repo", "delete"], rc=0)
    code, out, _ = run_cmd(capsys, "project", "delete-repo", "alpha")
    assert code == 0 and "alpha is deleted." in out
    assert run_cmd(capsys, "project", "delete-repo", "ghost")[0] == 1


@pytest.mark.parametrize("who", ["chat:alpha", "chat:delegate", "agent"])
def test_cli_refuses_chat_callers(env, capsys, unitdir, monkeypatch, at_terminal, who):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha", "--who", who)
    assert code == 1 and "Only Alex" in err
    monkeypatch.setenv("PHOENIX_WHO", who)
    assert run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")[0] == 1
    assert run_cmd(capsys, "project", "delete-repo", "alpha")[0] == 1
    _all_there(folder)


def test_api_delete_guard_rejections(api):
    from test_api_server import make_project
    make_project("alpha")
    for path in ("/api/projects/alpha/delete", "/api/projects/alpha/delete-repo"):
        assert api(path, "POST", {k: v for k, v in POST_HEADERS.items() if k != "X-Phoenix"}, {"confirm": "alpha"})[0] == 403
        assert api(path, "POST", {**POST_HEADERS, "Origin": "http://evil.example"}, {"confirm": "alpha"})[0] == 403
    assert (paths.projects() / "alpha").is_dir()


def test_api_delete_wrong_confirm_400(api):
    from test_api_server import make_project
    make_project("alpha")
    for body in ({}, {"confirm": "alph"}, {"confirm": True}):
        status, resp = api("/api/projects/alpha/delete", "POST", POST_HEADERS, body)
        assert status == 400 and resp["ok"] is False
    assert (paths.projects() / "alpha").is_dir()


def test_api_delete_refused_409(api):
    from test_api_server import make_project
    make_project("alpha")
    make_project("phoenix9")
    status, resp = api("/api/projects/phoenix9/delete", "POST", POST_HEADERS, {"confirm": "phoenix9"})
    assert status == 409 and "deleted" in resp["message"]
    make_run("alpha", "r1", "running")
    status, resp = api("/api/projects/alpha/delete", "POST", POST_HEADERS, {"confirm": "alpha"})
    assert status == 409 and "build is running" in resp["message"]
    assert (paths.projects() / "alpha").is_dir()


def test_api_delete_works_and_repo_retry(api):
    from test_api_server import make_project
    folder = make_project("alpha")
    status, resp = api("/api/projects/alpha/delete", "POST", POST_HEADERS, {"confirm": "alpha"})
    assert status == 200 and resp["data"]["steps"][-1]["step"] == "GitHub repo" and not folder.exists()
    status, resp = api("/api/projects/alpha/delete-repo", "POST", POST_HEADERS, {})
    assert status == 200 and resp["data"]["name"] == "alpha"
    assert api("/api/projects/ghost/delete-repo", "POST", POST_HEADERS, {})[0] == 404


# ---- whose GitHub repo it is (finding 1) ----

def _gh_deletes(env):
    return [c for c in env["host"].calls if c[:3] == ["gh", "repo", "delete"]]


def _shared_parent(env):
    """The projects folder is itself a git repo (like /srv/projects, the notes repo of every project)."""
    git_repo(env["projects"], origin_url="https://github.com/me/projects.git", commit=False)


@pytest.mark.parametrize("meta", [None, {"source": "empty", "repo": "me/projects"}])
def test_plain_code_folder_never_deletes_parent_repo(env, unitdir, meta):
    _shared_parent(env)
    folder = make(env, "plain", meta=meta)
    (folder / "code").mkdir()
    (folder / "code" / "f.txt").write_text("f")
    host_git(env["host"], folder)
    plan = project_delete.plan("plain", "cli", env["fakes"])
    assert plan["repo"] == "me/projects" and plan["repo_delete"]["delete"] is False
    assert plan["repo_delete"]["why"].startswith("GitHub repo me/projects not deleted: it ")
    res = project_delete.delete("plain", "plain", "cli", env["fakes"])
    assert not folder.exists() and _gh_deletes(env) == []
    gh = res["steps"][-1]
    assert gh["step"] == "GitHub repo" and gh["ok"] and gh.get("kept") and "not deleted" in gh["words"]
    assert res["not_done"] == []


def test_own_repo_is_deleted(env, unitdir):
    _stuff(env)
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["repo_delete"]["delete"] is True
    project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [["gh", "repo", "delete", "me/alpha", "--yes"]]


@pytest.mark.parametrize("source", ["repo", "import", "code", None])
def test_repo_not_made_by_phoenix_is_kept(env, unitdir, source):
    folder = _stuff(env)
    meta = json.loads((folder / ".phoenix" / "project.json").read_text())
    meta["source"] = source
    (folder / ".phoenix" / "project.json").write_text(json.dumps(meta))
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and "was not created by Phoenix" in res["steps"][-1]["words"]


def test_origin_must_match_recorded_repo(env, unitdir):
    folder = _stuff(env)
    subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/me/other.git"], cwd=folder / "code", check=True)
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and "not this project's own repo" in res["steps"][-1]["words"]


def test_two_projects_sharing_a_repo(env, unitdir):
    _stuff(env)
    make(env, "beta", meta={"repo": "https://github.com/Me/Alpha.git", "source": "repo"})
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["repo_delete"]["delete"] is False and "shared" in plan["repo_delete"]["why"]
    assert "beta" in plan["repo_delete"]["why"]
    project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == []


def test_removed_row_sharing_the_repo(env, unitdir):
    folder = _stuff(env)
    _save_removed([{"name": "gamma", "path": "/x/gamma", "repo": "me/alpha", "removed_on": "2026-01-01"}])
    assert project_delete.plan("alpha", "cli", env["fakes"])["repo_delete"]["delete"] is False
    assert folder.is_dir()


def test_projects_folder_remote_is_never_deleted(env, unitdir):
    _stuff(env)
    subprocess.run(["git", "init", "-q"], cwd=env["projects"], check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:me/alpha.git"], cwd=env["projects"], check=True)
    plan = project_delete.plan("alpha", "cli", env["fakes"])
    assert plan["repo_delete"]["delete"] is False and "shared" in plan["repo_delete"]["why"]


# ---- GitHub only after a bundle of that repo and the folder is gone (finding 2) ----

def test_no_github_delete_when_folder_stays(env, unitdir):
    folder = _stuff(env)
    real = env["host"].remove_tree
    env["host"].remove_tree = lambda p: None if str(p) == str(folder) else real(p)
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert folder.is_dir() and _gh_deletes(env) == []
    gh = res["steps"][-1]
    assert gh["step"] == "GitHub repo" and not gh["ok"] and "folder" in gh["words"]
    assert any("GitHub repo me/alpha" in n["what"] for n in res["not_done"])


def test_no_github_delete_without_bundle(env, unitdir, monkeypatch):
    _stuff(env)
    monkeypatch.setattr(project_delete, "_bundle", lambda host, code, dest: "pretend there was no bundle")
    res = project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and res["steps"][-1]["kept"] and "bundle" in res["steps"][-1]["words"]


def test_no_github_delete_when_bundle_is_of_another_repo(env, unitdir):
    folder = _stuff(env)
    dest = project_delete.backup("alpha", "cli", env["fakes"])
    m = json.loads((dest / "manifest.json").read_text())
    assert m["bundle_of"] == "me/alpha"
    m["bundle_of"] = "me/other"
    (dest / "manifest.json").write_text(json.dumps(m))
    import shutil
    shutil.rmtree(folder)
    env["host"].script(["gh", "repo", "delete"], rc=0)
    res = project_delete.delete_repo("alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and "bundle" in res["steps"][-1]["words"]


# ---- only Alex, at a terminal (finding 4) ----

def test_cli_delete_needs_a_terminal(env, capsys, unitdir):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")
    assert code == 1 and "terminal" in err
    _all_there(folder)
    assert not [c for c in env["host"].calls if c[0] in ("remove_tree", "gh")]


def test_cli_delete_repo_needs_a_terminal(env, capsys, unitdir):
    from test_project_cmds import run_cmd
    assert run_cmd(capsys, "project", "delete-repo", "alpha")[0] == 1


def test_cli_delete_typed_name_must_match(env, capsys, unitdir, monkeypatch):
    from test_project_cmds import run_cmd
    from phoenix9.cli import project as cli_project
    folder = _stuff(env)
    monkeypatch.setattr(cli_project, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli_project, "_ask", lambda prompt: "alph")
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")
    assert code == 1 and "did not match" in err
    _all_there(folder)


def test_cli_delete_asks_for_the_name(env, capsys, unitdir, at_terminal):
    from test_project_cmds import run_cmd
    _stuff(env)
    assert run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha")[0] == 0
    assert at_terminal and "Type alpha " in at_terminal[0]


@pytest.mark.parametrize("who", ["runner", "phoenix-agent", "chat:home"])
def test_cli_who_must_be_cli_or_dashboard(env, capsys, unitdir, at_terminal, who):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha", "--who", who)
    assert code == 1 and "Only Alex" in err
    _all_there(folder)


def test_chat_env_cannot_be_overridden_with_who(env, capsys, unitdir, at_terminal, monkeypatch):
    from test_project_cmds import run_cmd
    folder = _stuff(env)
    monkeypatch.setenv("PHOENIX_WHO", "chat:alpha")
    code, _, err = run_cmd(capsys, "project", "delete", "alpha", "--confirm", "alpha", "--who", "cli")
    assert code == 1 and "Only Alex" in err
    assert run_cmd(capsys, "project", "delete-repo", "alpha", "--who", "dashboard")[0] == 1
    _all_there(folder)


def test_chat_units_say_who_they_are():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert "Environment=PHOENIX_WHO=chat:%i" in (root / "deploy" / "claude-rc-chat@.service").read_text()
    agent = json.loads((root / "deploy" / "agent" / "settings.json").read_text())
    assert agent["env"]["PHOENIX_WHO"] == "chat:home"


# ---- keep_days and a prune that cannot stop the runner (finding 5) ----

@pytest.mark.parametrize("raw,want", [("0", 1), ("-5", 1), ("1", 1), ("45", 45), ("3650", 3650), ("99999", 3650),
                                      ('"x"', 30), ("true", 30), ("2.5", 30)])
def test_keep_days_clamped(env, raw, want):
    from phoenix9 import settings
    (env["home"] / "config").mkdir(exist_ok=True)
    (env["home"] / "config" / "global.toml").write_text(f"[delete]\nkeep_days = {raw}\n")
    assert settings.delete_settings()["keep_days"] == want


def test_keep_days_zero_does_not_wipe_todays_copy(env):
    (env["home"] / "config").mkdir()
    (env["home"] / "config" / "global.toml").write_text("[delete]\nkeep_days = 0\n")
    fresh = _fake_copy("b", "20261106-2300")
    now = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc).timestamp()
    assert project_delete.prune_backups(env["fakes"], now) == [] and fresh.exists()


def test_runner_prune_never_raises(env, monkeypatch, capsys):
    from phoenix9 import watch

    def boom(adapters, now):
        raise PermissionError("no access")
    monkeypatch.setattr(watch.project_delete, "prune_backups", boom)
    watch.prune_deleted_copies(env["fakes"])
    assert "no access" in capsys.readouterr().err


# ---- only pure caches are left out (finding 6) ----

def test_without_git_build_output_is_kept(env):
    folder = make(env, "plain")
    code = folder / "code"
    for d in ("dist", "build", "target", ".cache", "pkg.egg-info", "node_modules", ".venv", ".turbo"):
        (code / d).mkdir(parents=True)
        (code / d / "f").write_text("x")
    (folder / "site" / "build").mkdir(parents=True)
    (folder / "site" / "build" / "index.html").write_text("x")
    (folder / "site" / "__pycache__").mkdir()
    (folder / "site" / "__pycache__" / "m.pyc").write_text("x")
    dest = project_delete.backup("plain", "cli", env["fakes"])
    names = _names(dest / "files.tar.gz")
    for kept in ("code/dist/f", "code/build/f", "code/target/f", "code/.cache/f", "code/pkg.egg-info/f",
                 "site/build/index.html"):
        assert kept in names, kept
    assert not [n for n in names if "node_modules" in n or ".venv" in n or ".turbo" in n or "__pycache__" in n]


# ---- links and protected projects under another name (finding 7) ----

def test_refuses_a_linked_project_folder(env, unitdir, tmp_path):
    outside = tmp_path / "elsewhere" / "real"
    (outside / "notes").mkdir(parents=True)
    (outside / "CLAUDE.md").write_text("# real\n")
    (env["projects"] / "alias").symlink_to(outside)
    plan = project_delete.plan("alias", "cli", env["fakes"])
    assert any("link" in r for r in plan["refusals"])
    with pytest.raises(OpsError, match="link"):
        project_delete.delete("alias", "alias", "cli", env["fakes"])
    assert (outside / "CLAUDE.md").is_file() and (env["projects"] / "alias").is_symlink()
    assert not paths.deleted_projects().exists() or list(paths.deleted_projects().iterdir()) == []


def test_refuses_a_link_to_a_protected_project(env, unitdir):
    real = make(env, "phoenix9")
    (env["projects"] / "p9").symlink_to(real)
    refusals = project_delete.plan("p9", "cli", env["fakes"])["refusals"]
    assert any("phoenix9 is Phoenix itself" in r for r in refusals)
    with pytest.raises(OpsError):
        project_delete.delete("p9", "p9", "cli", env["fakes"])
    assert (real / "CLAUDE.md").is_file()


def test_projects_root_may_itself_be_a_link(env, unitdir, tmp_path, monkeypatch):
    """/srv/projects is a link to the Docker volume: a normal project inside it is still fine."""
    folder = make(env, "alpha")
    link = tmp_path / "srv-projects"
    link.symlink_to(env["projects"])
    monkeypatch.setenv("PHOENIX_PROJECTS", str(link))
    assert project_delete.plan("alpha", "cli", env["fakes"])["refusals"] == []
    assert folder.is_dir()


# ---- the Delete repo retry (finding 8) ----

from phoenix9.ops.common import Conflict  # noqa: E402


def _deleted_with_repo_left(env):
    _stuff(env)
    env["host"].script(["gh", "repo", "delete"], rc=1, err="needs delete_repo scope")
    project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    env["host"].script(["gh", "repo", "delete"], rc=0)
    env["host"].calls.clear()


def test_retry_refused_when_folder_is_back(env, unitdir):
    _deleted_with_repo_left(env)
    make(env, "alpha")
    with pytest.raises(Conflict, match="exists again"):
        project_delete.delete_repo("alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == []


def test_retry_refused_when_another_project_uses_the_repo(env, unitdir):
    _deleted_with_repo_left(env)
    make(env, "beta", meta={"repo": "me/alpha", "source": "repo"})
    with pytest.raises(Conflict, match="beta"):
        project_delete.delete_repo("alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == []


def test_retry_keeps_a_repo_the_copy_does_not_vouch_for(env, unitdir):
    _deleted_with_repo_left(env)
    copy = project_delete._newest_copy("alpha")
    m = json.loads((copy / "manifest.json").read_text())
    del m["repo_delete"]
    (copy / "manifest.json").write_text(json.dumps(m))
    res = project_delete.delete_repo("alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and res["steps"][0]["kept"]


def test_retry_keeps_a_repo_that_was_never_phoenixs(env, unitdir):
    folder = _stuff(env)
    meta = json.loads((folder / ".phoenix" / "project.json").read_text())
    (folder / ".phoenix" / "project.json").write_text(json.dumps({**meta, "source": "repo"}))
    project_delete.delete("alpha", "alpha", "cli", env["fakes"])
    res = project_delete.delete_repo("alpha", "cli", env["fakes"])
    assert _gh_deletes(env) == [] and res["steps"][0]["kept"]
