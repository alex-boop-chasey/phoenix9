"""Delete project, dry run: the plan lists everything that would go and the refusals; nothing is touched."""
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
