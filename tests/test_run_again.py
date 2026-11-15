"""Run again: a failed or stopped build starts again with the same spec, reference documents and settings."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from phoenix9 import atomic, events, paths, reference, settings, state
from phoenix9.api import server
from phoenix9.ops import common, repair as ops_repair, runs as runs_ops

SPEC = "# Spec: Add Login\n\n## Task 1: First\nGoal: do it.\nDone when:\n- the login page shows a form\n"
POST_HEADERS = {"X-Phoenix": "1", "Origin": "https://phoenix.rebirthwebdesign.com.au", "Content-Type": "application/json"}


@pytest.fixture
def env(phoenix_env, tmp_path, monkeypatch):
    """Fake adapters injected into ops and one project "demo" with a project type."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    claude = tmp_path / "claude.json"
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude))
    fakes.host.files[str(claude)] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# demo\n\nAbout demo.\n\n- Profile: python-script\n- Repo: (none yet)\n")
    (folder / "phoenix.toml").write_text('profile = "python-script"\n')
    return {"tmp": tmp_path, "folder": folder}


def first_run(env, overrides=None, status="failed", project="demo"):
    """Start a run and end it with this status; returns its id."""
    spec = env["tmp"] / "spec.md"
    spec.write_text(SPEC)
    run_id = runs_ops.start(project, spec, overrides)["run_id"]
    state.update(paths.runs(project) / run_id, lambda s: s.__setitem__("status", status))
    return run_id


def overrides_of(run_id, project="demo"):
    return atomic.read_json(paths.runs(project) / run_id / "overrides.json")


CUSTOM = {"preset": "custom", "based_on": "full", "steps": {"verify": {"on": False}}}


def test_custom_run_comes_back_with_identical_overrides(env):
    old = first_run(env, dict(CUSTOM))
    out = runs_ops.run_again("demo", old)
    assert out["from_run"] == old and out["run_id"] != old and out["status"] == "queued"
    assert out["project"] == "demo" and out["preset"] == "custom"
    assert overrides_of(out["run_id"]) == overrides_of(old) == CUSTOM
    new_spec = paths.runs("demo") / out["run_id"] / "spec.md"
    assert new_spec.read_text() == SPEC


def test_preset_change_keeps_everything_else(env):
    old = first_run(env, dict(CUSTOM), status="stopped")
    out = runs_ops.run_again("demo", old, preset="quick")
    assert overrides_of(out["run_id"]) == {**CUSTOM, "preset": "quick"} and out["preset"] == "quick"


def test_custom_needs_a_based_on(env):
    old = first_run(env, {"preset": "full"})
    with pytest.raises(common.OpsError, match="custom preset needs"):
        runs_ops.run_again("demo", old, preset="custom")
    with pytest.raises(common.OpsError, match="not a preset"):
        runs_ops.run_again("demo", old, preset="nope")
    settings.save_project(env["folder"], {"profile": "python-script", "based_on": "full"})
    out = runs_ops.run_again("demo", old, preset="custom")
    assert overrides_of(out["run_id"]) == {"preset": "custom"}


def test_reference_folder_is_copied_from_the_old_run(env):
    reference.add_file("demo", "brand.css", b"a{color:red}", "alex")
    old = first_run(env)
    reference.add_file("demo", "brand.css", b"a{color:blue}", "alex")
    reference.add_file("demo", "later.css", b"b{}", "alex")
    out = runs_ops.run_again("demo", old)
    old_snap = paths.runs("demo") / old / "reference"
    snap = paths.runs("demo") / out["run_id"] / "reference"
    assert (snap / "brand.css").read_bytes() == b"a{color:red}"
    assert not (snap / "later.css").exists()
    assert (snap / "INDEX.md").read_text() == (old_snap / "INDEX.md").read_text()
    assert oct((snap / "brand.css").stat().st_mode & 0o777) == "0o444"
    got = [e for e in events.read(paths.events()) if e["type"] == "reference.snapshot" and e["run"] == out["run_id"]]
    assert len(got) == 1 and got[0]["data"]["copied_from"] == old and got[0]["data"]["files"] == 1


def test_no_reference_folder_stays_none(env):
    old = first_run(env)
    reference.add_file("demo", "brand.css", b"a{}", "alex")       # added after the first run: not part of it
    out = runs_ops.run_again("demo", old)
    assert not (paths.runs("demo") / out["run_id"] / "reference").exists()


@pytest.mark.parametrize("status", ["running", "done", "queued"])
def test_refused_unless_failed_or_stopped(env, status):
    old = first_run(env, status=status)
    with pytest.raises(common.Conflict, match="only a failed or stopped build"):
        runs_ops.run_again("demo", old)


def test_refused_for_another_project(env):
    old = first_run(env)
    (paths.projects() / "other").mkdir()
    with pytest.raises(common.NotFound):
        runs_ops.run_again("other", old)


def test_agent_keeps_a_safety_key_but_cannot_change_one(env):
    old = first_run(env, {"on_failure": "continue"})
    with pytest.raises(common.OpsError, match="may not start a build"):     # a new start with it is refused
        runs_ops.start("demo", paths.runs("demo") / old / "spec.md", {"on_failure": "continue"}, who="agent")
    out = runs_ops.run_again("demo", old, who="agent")
    assert overrides_of(out["run_id"]) == {"on_failure": "continue"}
    with pytest.raises(TypeError):                                          # there is no way to pass other changes
        runs_ops.run_again("demo", old, overrides={"on_failure": "pause"}, who="agent")


def test_chat_without_permission_is_refused(env):
    old = first_run(env)
    with pytest.raises(common.Conflict, match="may not repair"):
        runs_ops.run_again("demo", old, who="chat:demo")


def test_old_run_records_the_new_id(env):
    old = first_run(env)
    out = runs_ops.run_again("demo", old, who="dashboard")
    notes = [e for e in events.read(paths.events()) if e["type"] == "run.note" and e["run"] == old]
    assert notes and notes[-1]["data"]["note"] == f"Run again as {out['run_id']}"
    assert notes[-1]["data"]["who"] == "dashboard"
    cmds = [e for e in events.read(paths.events()) if e["type"] == "command"]
    assert any(e["data"].get("command") == f"run again {old}" for e in cmds) or \
        any(f"run again {old}" in json.dumps(e["data"]) for e in cmds)


def test_restart_on_preset_carries_the_reference_copy(env):
    reference.add_file("demo", "brand.css", b"old{}", "alex")
    old = first_run(env, {"preset": "quick"})
    reference.add_file("demo", "brand.css", b"new{}", "alex")
    out = ops_repair.restart_on_preset("demo", old, "full", who="agent")
    new = paths.runs("demo") / out["new_run_id"]
    assert (new / "reference" / "brand.css").read_bytes() == b"old{}"
    assert overrides_of(out["new_run_id"]) == {"preset": "full"}
    atomic.write_json(paths.runs("demo") / old / "settings.json", {"preset": "quick"})   # as a run that ran has
    with pytest.raises(common.Conflict, match="use Run again"):
        ops_repair.restart_on_preset("demo", old, "quick", who="agent")


def test_cli_needs_yes(env, capsys):
    from phoenix9.__main__ import main
    old = first_run(env)
    assert main(["run", "again", old]) != 0
    assert len(runs_ops.list_("demo")) == 1
    assert main(["run", "again", old, "--yes"]) == 0
    assert "again as" in capsys.readouterr().out
    assert len(runs_ops.list_("demo")) == 2


@pytest.fixture
def api(env, dist):
    """A running API server on a free port; returns a POST function."""
    httpd = server.make_server(0, web_dist=dist)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers=POST_HEADERS)
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError as err:
            resp = err
        content = resp.read()
        resp.close()
        return resp.status, json.loads(content)
    yield post
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / "index.html").write_text("<html>app</html>")
    return folder


def test_api_needs_confirm(env, api):
    old = first_run(env)
    code, body = api(f"/api/runs/demo/{old}/again", {})
    assert code == 400 and "needs confirmation" in json.dumps(body)
    assert len(runs_ops.list_("demo")) == 1
    code, body = api(f"/api/runs/demo/{old}/again", {"confirm": True, "preset": "full"})
    assert code == 200 and body["ok"], body
    body = body["data"]
    assert body["from_run"] == old and body["preset"] == "full"
    assert overrides_of(body["run_id"]) == {"preset": "full"}
