"""Delete project, dry run: the plan lists everything that would go and the refusals; nothing is touched."""
import datetime
import json
import subprocess

import pytest

from phoenix9 import atomic, deploy, keys, paths, project_delete
from phoenix9.ops.common import NotFound
from test_project_cmds import env, make  # noqa: F401  (fixtures)

PR_JSON = json.dumps([{"number": 7, "title": "Add x", "url": "https://github.com/me/alpha/pull/7"}])


def git_repo(code, remote=None):
    """A real tiny repo in `code` with one commit (and an optional origin that has it)."""
    code.mkdir(parents=True)
    run = lambda *a, cwd=code: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    (code / "a.txt").write_text("a")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    if remote:
        run("clone", "-q", "--bare", str(code), str(remote), cwd=code.parent)
        run("remote", "add", "origin", str(remote))
        run("fetch", "-q", "origin")


def host_git(host, folder):
    """Make the fake host really run git commands."""
    def run(argv, timeout=60, cwd=None):
        host.calls.append(list(argv))
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
    folder = make(env, name, meta={"repo": "me/alpha"})
    git_repo(folder / "code")
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
    assert "code/a.txt" not in names                       # tracked: it is in the bundle
    assert not [n for n in names if "node_modules" in n or "__pycache__" in n or "dist" in n or ".git/" in n]


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
