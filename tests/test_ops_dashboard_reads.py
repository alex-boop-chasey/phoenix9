"""The read-only ops the dashboard API needs, and the docs/api.md contract."""
import importlib
import json
import re
from pathlib import Path

import pytest

import phoenix9
from phoenix9 import atomic, gates as gates_core, keys as keys_core, runs as runs_core, state
from phoenix9.__main__ import main
from phoenix9.ops.common import OpsError
from phoenix9.ops import app, common, github, gates as gates_ops, keys as keys_ops, projects, runs as runs_ops

SPEC = "# Spec: Add Login\n\n## Task 1: First\nGoal: do it.\nDone when:\n- the login page shows a form\n"
ROW_KEYS = {"name", "description", "path", "repo", "repo_owner", "repo_name", "profile", "services", "size",
            "vscode_url", "vscode", "last_used", "last_used_at", "harness", "has_phoenix_toml",
            "repo_url", "needs_you", "run", "last_build_failed", "questions", "activity", "status_line", "run_text", "worker", "chat"}


@pytest.fixture
def env(phoenix_env, tmp_path, monkeypatch):
    """Fake adapters injected into ops."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    claude = tmp_path / "claude.json"
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude))
    fakes.host.files[str(claude)] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    return {"fakes": fakes, "host": fakes.host, "projects": phoenix_env["projects"], "home": phoenix_env["home"],
            "tmp": tmp_path}


def make(env, name="demo", repo="(none yet)"):
    folder = env["projects"] / name
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text(f"# {name}\n\nAbout {name}.\n\n- Profile: python-script\n- Repo: {repo}\n")
    (folder / "phoenix.toml").write_text('profile = "python-script"\n')
    if "/" in repo:
        atomic.write_json(folder / ".phoenix" / "project.json", {"repo": repo})
    return folder


def queue_run(env, project="demo", overrides=None):
    spec = env["tmp"] / "spec.md"
    spec.write_text(SPEC)
    return runs_ops.start(project, spec, overrides)["run_id"]


def test_info_reports_version_and_update_not_installed(env):
    env["host"].script(["gh", "auth", "status"], rc=1)
    data = app.info()
    assert data["version"] == phoenix9.__version__
    assert data["label"] == "v9.1" and app.info("v9.2")["label"] == "v9.2"
    assert data["update"]["supported"] is True and data["update"]["available"] is False
    assert data["update"]["can_install"] is False and "not installed" in data["update"]["reason"]
    assert data["github"] == {"connected": False, "accounts": []}
    assert data["services"] == {"supported": True}


def test_rows_have_every_documented_field(env):
    make(env)
    [row] = projects.rows()
    assert set(row) == ROW_KEYS
    assert row["repo_url"] is None and row["needs_you"] == 0 and row["run"] is None
    assert isinstance(row["harness"], str)


def test_rows_needs_you_and_active_run(env):
    make(env, "alpha", repo="octo/alpha")
    make(env, "beta")
    run_id = queue_run(env, "alpha")
    folder = runs_core.find_run(run_id)
    gates_core.open_gate(folder, kind="merge", title="Merge?", why="because")
    rows = {r["name"]: r for r in projects.rows()}
    assert rows["alpha"]["needs_you"] == 1
    assert rows["alpha"]["repo_url"] == "https://github.com/octo/alpha"
    assert rows["alpha"]["run"]["run_id"] == run_id and rows["alpha"]["run"]["status"] == "waiting"
    assert rows["alpha"]["run"]["tasks"] == 1
    assert rows["beta"]["needs_you"] == 0 and rows["beta"]["run"] is None
    state.set_status(folder, "done")
    assert {r["name"]: r for r in projects.rows()}["alpha"]["run"] is None


def test_check_name_rejects_bad_and_existing_names(env):
    make(env, "taken")
    assert projects.check_name("fresh-name")["ok"] is True
    assert projects.check_name("Bad Name")["ok"] is False
    assert "already exists" in projects.check_name("taken")["message"]


def test_changelog_parses_lines_newest_last(env):
    folder = make(env)
    (folder / "notes" / "changelog.md").write_text(
        "# Changelog\n- 2026-01-01 · alex · first\n- plain old line\n- 2026-01-02 · dashboard · second · more\n")
    assert projects.changelog("demo") == [
        {"date": "2026-01-01", "who": "alex", "text": "first"},
        {"date": "", "who": "", "text": "plain old line"},
        {"date": "2026-01-02", "who": "dashboard", "text": "second · more"}]
    assert [c["text"] for c in projects.changelog("demo", limit=1)] == ["second · more"]
    with pytest.raises(common.NotFound):
        projects.changelog("nope")


def test_specs_lists_specs_and_plans_markdown_only(env):
    import os
    folder = make(env)
    (folder / "notes" / "specs").mkdir()
    (folder / "notes" / "plans").mkdir()
    old = folder / "notes" / "specs" / "a.md"
    old.write_text("intro\n# First spec\n")
    os.utime(old, (1000, 1000))
    (folder / "notes" / "plans" / "b.md").write_text("no heading here\n")
    (folder / "notes" / "specs" / "c.txt").write_text("# not markdown\n")
    found = projects.specs("demo")
    assert [f["path"] for f in found] == ["plans/b.md", "specs/a.md"]
    assert found[1]["title"] == "First spec" and found[0]["title"] == "b"
    assert set(found[0]) == {"path", "title", "modified"}


def test_keys_rows_records_no_command(env):
    make(env)
    keys_core.set_key("demo", "API_TOKEN", "s3cret-value", True)
    rows = keys_ops.rows("demo")
    assert rows[0]["name"] == "API_TOKEN" and "s3cret-value" not in json.dumps(rows)
    assert not (env["home"] / "logs" / "commands.jsonl").exists()
    keys_ops.list_("demo", "cli")
    assert (env["home"] / "logs" / "commands.jsonl").exists()


def test_github_not_connected_when_gh_auth_fails(env):
    env["host"].script(["gh", "auth", "status"], rc=1, err="not logged in")
    assert github.status() == {"connected": False, "accounts": []}
    assert github.repos() == {"connected": False, "repos": []}


def test_github_repos_lists_each_account(env):
    host = env["host"]
    host.script(["gh", "api", "user", "--jq"], out="alex\n")
    host.script(["gh", "api", "user/orgs"], out="acme\n")
    host.script(["gh", "repo", "list", "alex"], out=json.dumps([{"nameWithOwner": "alex/one", "isPrivate": True}]))
    host.script(["gh", "repo", "list", "acme"], out=json.dumps([{"nameWithOwner": "acme/two", "isPrivate": False}]))
    assert github.status() == {"connected": True, "accounts": ["alex", "acme"]}
    assert github.repos()["repos"] == [{"full_name": "alex/one", "owner": "alex", "private": True},
                                       {"full_name": "acme/two", "owner": "acme", "private": False}]


def test_builds_have_title_preset_duration_cost(env):
    make(env)
    run_id = queue_run(env)
    folder = runs_core.find_run(run_id)
    state.update(folder, lambda s: s["usage"].update(cost_usd=0.5))
    [build] = runs_ops.builds("demo")
    assert build["run_id"] == run_id and build["cost"] == "$0.50"
    assert {"title", "preset", "started", "finished", "duration", "tasks_failed"} <= set(build)
    assert build["tasks_failed"] == 0 and build["status"] == "queued"


def test_detail_of_queued_run_has_preview_plan(env):
    make(env)
    run_id = queue_run(env, overrides={"max_tries": 4})
    data = runs_ops.detail("demo", run_id)
    assert data["plan_frozen"] is False and "groups" in data["plan"] and data["plan"]["steps"]
    assert data["max_tries"] == 4 and data["run_id"] == run_id
    assert {"title", "preset", "gates", "recent_events"} <= set(data)


def test_detail_wrong_project_not_found(env):
    make(env, "alpha")
    make(env, "beta")
    run_id = queue_run(env, "alpha")
    with pytest.raises(common.NotFound):
        runs_ops.detail("beta", run_id)
    with pytest.raises(common.NotFound):
        runs_ops.detail("alpha", "no-such-run")


def test_not_found_and_conflict_are_ops_errors(env, capsys):
    make(env)
    assert issubclass(common.NotFound, common.OpsError) and issubclass(common.Conflict, common.OpsError)
    run_id = queue_run(env)
    gate = gates_core.open_gate(runs_core.find_run(run_id), kind="merge", title="Merge?", why="x")
    gates_ops.answer(gate["id"], "approve", who="dashboard")
    with pytest.raises(common.Conflict):
        gates_ops.answer(gate["id"], "approve", who="dashboard")
    with pytest.raises(common.NotFound):
        gates_ops.answer("nope.g1", "approve")
    code = main(["gate", "answer", gate["id"], "approve"])
    err = capsys.readouterr()
    assert code == 1 and "already answered" in (err.err + err.out)
    code = main(["project", "show", "ghost"])
    err = capsys.readouterr()
    assert code == 1 and "There is no project called 'ghost'." in (err.err + err.out)


def test_api_md_mentions_every_ops_function_it_names_exists():
    text = (Path(__file__).resolve().parent.parent / "docs" / "api.md").read_text()
    checked = 0
    for line in text.splitlines():
        if "step 03" in line or "step 04" in line or "phase 4" in line:
            continue
        for module, func in re.findall(r"`ops\.([a-z_]+)\.([a-z_]+)`", line):
            mod = importlib.import_module(f"phoenix9.ops.{module}")
            assert callable(getattr(mod, func)), f"ops.{module}.{func}"
            checked += 1
    assert checked >= 15


def test_api_doc_lists_every_route():
    from phoenix9.api.server import ROUTES

    def norm(path):
        path = re.sub(r"\(\?P<\w+>[^)]*\)", "<>", path)
        return re.sub(r"<\w+>", "<>", path.split("?")[0])

    text = (Path(__file__).resolve().parent.parent / "docs" / "api.md").read_text()
    documented = {(m, norm(p)) for m, p in re.findall(r"^\| (GET|POST) \| `([^`]+)`", text, re.M)}
    for method, pattern, _ in ROUTES:
        assert (method, norm(pattern)) in documented, f"{method} {pattern} is not in docs/api.md"


def test_library_presets_have_titles_and_descriptions(env):
    from phoenix9.ops import library
    rows = {r["name"]: r for r in library.presets()["presets"]}
    assert rows["quick"]["title"] == "Quick"
    assert rows["quick"]["has_file"] is True
    assert rows["quick"]["description"].startswith("Simple, plus")
    assert rows["custom"] == {"name": "custom", "title": "Custom", "has_file": False, "description": library.CUSTOM_DESCRIPTION, "steps": {}}


def _finish(run_id, status):
    state.set_status(runs_core.find_run(run_id), status)


def _state(name="demo"):
    return projects.state_of({r["name"]: r for r in projects.rows()}[name])


def test_state_latest_build_failed_is_fail(env):
    make(env)
    _finish(queue_run(env), "failed")
    assert _state() == "fail"
    assert projects.query()["counts"]["fail"] == 1
    assert projects.row("demo")["last_build_failed"] is True


def test_state_failed_then_passed_later_is_idle(env):
    make(env)
    _finish(queue_run(env), "failed")
    second = queue_run(env)
    state.update(runs_core.find_run(second), lambda s: s.__setitem__("created", "9999-01-01T00:00:00Z"))
    _finish(second, "done")
    assert _state() == "idle"


def test_state_failed_but_new_run_running_is_run(env):
    import time
    from phoenix9 import heartbeat
    heartbeat.write(time.time())          # the runner is alive (A6: no heartbeat = worker not responding)
    make(env)
    _finish(queue_run(env), "failed")
    newer = queue_run(env)
    state.update(runs_core.find_run(newer), lambda s: s.__setitem__("created", "9999-01-01T00:00:00Z"))
    _finish(newer, "running")
    assert _state() == "run"


def test_state_failed_and_gate_open_is_need(env):
    make(env)
    _finish(queue_run(env), "failed")
    newer = queue_run(env)
    gates_core.open_gate(runs_core.find_run(newer), kind="merge", title="Merge?", why="because")
    assert _state() == "need"


def test_answered_waiting_run_shows_as_running(tmp_path):
    """A waiting run with no open question left shows as running (carrying on) without the runner."""
    st = {"run_id": "r1", "status": "waiting", "steps": [{"step": "merge", "status": "waiting"}],
          "tasks": {"1": {"status": "waiting"}, "2": {"status": "passed"}}}
    from phoenix9 import status
    asking = status.seen_run(st, {"r1.1"})
    assert asking["status"] == "waiting"
    out = status.seen_run(st, set())
    assert out["status"] == "running" and out["carrying_on"] is True
    assert out["steps"][0]["status"] == "running" and out["steps"][0]["answered"] is True
    assert out["tasks"]["1"]["answered"] is True and out["tasks"]["2"]["status"] == "passed"


def test_run_start_marks_project_used(env):
    folder = make(env)
    queue_run(env)
    assert (folder / ".phoenix" / "last-used").exists()


def test_last_used_picks_newer_of_phoenix_and_proj_records(env):
    import os
    from phoenix9 import project
    folder = make(env)
    mine = folder / ".phoenix" / "last-used"
    mine.parent.mkdir(exist_ok=True)
    mine.touch()
    theirs = env["projects"] / ".proj" / "demo.used"
    theirs.parent.mkdir()
    theirs.touch()
    os.utime(mine, (1000, 1000))
    os.utime(theirs, (5000, 5000))
    assert project.last_used("demo", 5060)[0] == 5000
    os.utime(mine, (9000, 9000))
    assert project.last_used("demo", 9060)[0] == 9000
    mine.unlink()
    theirs.unlink()
    assert project.last_used("demo", 9060) == (None, "never")


def test_run_start_without_a_project_type_is_refused(env):
    folder = make(env)
    (folder / "phoenix.toml").unlink()
    spec = env["tmp"] / "spec.md"
    spec.write_text(SPEC)
    with pytest.raises(OpsError, match="demo has no project type yet.*phoenix settings set demo profile"):
        runs_ops.start("demo", spec)
    assert not (folder / ".phoenix" / "last-used").exists()
    assert runs_ops.start("demo", spec, {"profile": "web"})["status"] == "queued"   # a per-run profile counts


def test_run_start_with_a_project_type_proceeds(env):
    make(env)
    assert queue_run(env)
