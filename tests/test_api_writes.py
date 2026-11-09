"""Tests for the dashboard API write endpoints: create jobs, edit, keys, settings, wizard, runs and gates."""
import json
import time

import pytest

from phoenix9 import atomic, gates as gates_core, keys as keys_core, paths, runs as runs_core, settings
from phoenix9.api import server
from phoenix9.ops import common, keys as keys_ops, projects, runs as runs_ops
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

SPEC = "# Spec: Add Login\n\nProject: alpha\n\n## Task 1: First\nGoal: do it.\nDone when:\n- the login page shows a form\n"
SECRET = "sk-super-secret-value-123"


def post(api, path, body=None):
    return api(path, "POST", POST_HEADERS, body if body is not None else {})


def wait_job(api, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        status, body = api(f"/api/jobs/{job_id}")
        assert status == 200
        if body["data"]["status"] != "running":
            return body["data"]
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def form(**kw):
    return {"name": "newone", "description": "A new thing.", "source": {"kind": "empty"}, "profile": "python-script",
            "new_repo": {"on": False}, "services": [], "keys": [], **kw}


def add_spec(folder, text=SPEC, sub="specs", name="login.md"):
    (folder / "notes" / sub).mkdir(parents=True, exist_ok=True)
    (folder / "notes" / sub / name).write_text(text)
    return f"{sub}/{name}"


def open_gate(folder_project="alpha", kind="merge"):
    status = runs_ops.start(folder_project, paths.projects() / folder_project / "notes" / "specs" / "login.md")
    run_dir = runs_core.find_run(status["run_id"])
    return gates_core.open_gate(run_dir, kind=kind, title="Merge?", why="because"), status["run_id"]


# ---- create ----

def test_create_returns_job_and_progress_reaches_done(api):
    status, body = post(api, "/api/projects", form())
    assert status == 200 and len(body["data"]["job"]) == 12
    job = wait_job(api, body["data"]["job"])
    assert job["status"] == "done" and job["kind"] == "create" and job["project"] == "newone"
    labels = [s["label"] for s in job["steps"]]
    assert labels[0] == "Checking the form" and "Adding it to the project list" in labels
    assert all(s["status"] == "done" for s in job["steps"])
    assert (paths.projects() / "newone" / "CLAUDE.md").exists()


def test_create_failure_job_failed_with_message_and_nothing_left(api):
    status, body = post(api, "/api/projects", form(profile="no-such-profile"))
    job = wait_job(api, body["data"]["job"])
    assert job["status"] == "failed" and "Unknown profile" in job["message"]
    assert job["steps"][-1]["status"] == "failed"
    assert not (paths.projects() / "newone").exists()


def test_create_second_while_running_409(api, monkeypatch):
    import threading
    gate, started = threading.Event(), threading.Event()

    def slow(opts, who, progress=None):
        progress("Checking the form")
        started.set()
        gate.wait(5)
        return {}
    monkeypatch.setattr(projects, "new", slow)
    status, body = post(api, "/api/projects", form())
    assert status == 200
    started.wait(5)
    status, again = post(api, "/api/projects", form(name="other"))
    assert status == 409 and again["message"] == "Another project is being created; try again in a moment."
    gate.set()
    assert wait_job(api, body["data"]["job"])["status"] == "done"


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"source": {"kind": "weird"}}, {"source": {"kind": "repo"}}, {"services": "x"},
    {"keys": [{"name": "A"}]}, {"new_repo": {"on": True}}, {"profile": 5}, {"description": 5}])
def test_create_bad_shape_400(api, bad):
    status, body = post(api, "/api/projects", form(**bad))
    assert status == 400 and body["ok"] is False
    assert not (paths.projects() / "other").exists()


def test_create_with_keys_rows_saves_them_and_never_writes_a_keys_file(api, tmp_path):
    from fakes import fake_adapters
    from phoenix9 import project
    rows = [{"name": "API_KEY", "value": SECRET, "secret": True}, {"name": "REGION", "value": "au", "secret": False}]
    lines = []
    project.create({"name": "withkeys", "description": "d", "profile": "python-script", "no_new_repo": True,
                    "keys": rows}, common.make_adapters(), "dashboard", lines.append)
    assert "Saving keys" in lines
    assert keys_core.container_env("withkeys") == {"API_KEY": SECRET, "REGION": "au"}
    env_example = (paths.projects() / "withkeys" / "code" / ".env.example").read_text()
    assert SECRET not in env_example and "REGION=au" in env_example
    assert not list(tmp_path.rglob("*.keys.toml")) and not [p for p in paths.projects().rglob("*") if p.suffix == ".toml" and "key" in p.name]


# ---- edit ----

def test_edit_repo_needs_confirm_409_then_ok(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/edit", {"repo": "me/alpha"})
    assert status == 409 and body["needs_confirm"] is True
    assert body["message"] == "Changing the repo or profile needs confirmation."
    status, body = post(api, "/api/projects/alpha/edit", {"repo": "me/alpha", "confirm": True})
    assert status == 200 and body["data"]["name"] == "alpha"


def test_edit_description_and_nothing_to_change(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/edit", {"description": "New words."})
    assert status == 200 and "New words." in body["data"]["description"]
    status, body = post(api, "/api/projects/alpha/edit", {})
    assert status == 400 and "Nothing to change" in body["message"]


def test_edit_services_calls_set_services(api):
    folder = make_project("alpha")
    status, body = post(api, "/api/projects/alpha/edit", {"services": ["openrouter"]})
    assert status == 200
    assert settings.load_project(folder)["services"] == ["openrouter"]
    status, body = post(api, "/api/projects/alpha/edit", {"services": ["nonesuch"]})
    assert status == 400 and "Unknown service" in body["message"]


# ---- keys ----

def test_keys_save_masks_secrets(api):
    make_project("alpha")
    rows = [{"name": "TOKEN", "value": SECRET, "secret": True}, {"name": "REGION", "value": "au", "secret": False}]
    status, body = post(api, "/api/projects/alpha/keys/save", {"rows": rows})
    assert status == 200 and SECRET not in json.dumps(body)
    by = {r["name"]: r for r in body["data"]}
    assert by["TOKEN"]["value_if_not_secret"] is None and by["REGION"]["value_if_not_secret"] == "au"


def test_keys_save_keeps_secret_when_value_omitted(api):
    make_project("alpha")
    post(api, "/api/projects/alpha/keys/save", {"rows": [{"name": "TOKEN", "value": SECRET, "secret": True}]})
    status, body = post(api, "/api/projects/alpha/keys/save", {"rows": [{"name": "TOKEN", "secret": False}]})
    assert status == 200 and body["data"][0]["secret"] is False and body["data"][0]["has_value"] is True
    assert keys_core.container_env("alpha") == {"TOKEN": SECRET}


def test_keys_bad_name_duplicate_empty_400(api):
    make_project("alpha")
    rows = [{"name": "1BAD", "value": "x", "secret": True}, {"name": "A", "value": "x"}, {"name": "A", "value": "y"},
            {"name": "EMPTY", "value": ""}, {"name": "BREAK", "value": "a\nb"}]
    status, body = post(api, "/api/projects/alpha/keys/save", {"rows": rows})
    assert status == 400
    for word in ("1BAD", "more than once", "EMPTY", "BREAK"):
        assert word in body["message"]
    assert keys_core.list_keys("alpha") == []


def test_keys_reveal_returns_value_and_logs_nothing(api):
    make_project("alpha")
    post(api, "/api/projects/alpha/keys/save", {"rows": [{"name": "TOKEN", "value": SECRET, "secret": True}]})
    status, body = post(api, "/api/projects/alpha/keys/reveal", {"name": "TOKEN"})
    assert body["data"] == {"name": "TOKEN", "value": SECRET}
    assert post(api, "/api/projects/alpha/keys/reveal", {"name": "NOPE"})[0] == 404
    for path in (paths.logs() / "api.log", paths.events(), paths.logs() / "commands.jsonl"):
        text = path.read_text()
        assert SECRET not in text
    assert "project keys alpha reveal TOKEN" in (paths.logs() / "commands.jsonl").read_text()
    assert SECRET not in (paths.projects() / "alpha" / "notes" / "changelog.md").read_text()


def test_keys_remove(api):
    make_project("alpha")
    post(api, "/api/projects/alpha/keys/save", {"rows": [{"name": "TOKEN", "value": SECRET}]})
    status, body = post(api, "/api/projects/alpha/keys/remove", {"name": "TOKEN"})
    assert status == 200 and body["data"] == []
    assert post(api, "/api/projects/alpha/keys/remove", {"name": "TOKEN"})[0] == 400


# ---- settings ----

def test_settings_set_invalid_400_nothing_written(api):
    folder = make_project("alpha")
    before = (folder / "phoenix.toml").read_text() if (folder / "phoenix.toml").exists() else ""
    status, body = post(api, "/api/projects/alpha/settings",
                        {"set": {"max_tries": 5, "nope.key": 1, "merge": "sideways"}})
    assert status == 400 and "nope.key" in body["message"] and "merge" in body["message"]
    after = (folder / "phoenix.toml").read_text() if (folder / "phoenix.toml").exists() else ""
    assert before == after
    status, body = post(api, "/api/projects/alpha/settings", {"set": {"max_tries": 5, "steps.reviewer.on": True}})
    assert status == 200 and body["data"]["values"]["max_tries"] == 5
    assert settings.load_project(folder)["steps"]["reviewer"]["on"] is True


def test_settings_preset_resets(api):
    folder = make_project("alpha")
    post(api, "/api/projects/alpha/settings", {"set": {"steps.reviewer.on": True}})
    status, body = post(api, "/api/projects/alpha/settings/preset", {"preset": "full"})
    assert status == 200 and body["data"]["values"]["preset"] == "full"
    data = settings.load_project(folder)
    assert data["preset"] == "full" and "on" not in data.get("steps", {}).get("reviewer", {})
    assert post(api, "/api/projects/alpha/settings/preset", {"preset": "bogus"})[0] == 400


def test_settings_check(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/settings/check")
    assert status == 200 and "values" in body["data"]


# ---- wizard ----

def test_plan_for_overrides_no_write(api):
    folder = make_project("alpha")
    before = sorted(p.name for p in folder.iterdir())
    toml_before = (folder / "phoenix.toml").read_text()
    status, body = post(api, "/api/projects/alpha/plan", {"overrides": {"preset": "full"}})
    data = body["data"]
    assert status == 200 and data["errors"] == [] and data["settings"]["preset"] == "full"
    assert set(data["groups"]) == {"run-start", "task", "run-finish"}
    assert "planner" in data["groups"]["run-start"]
    row = next(r for r in data["steps"] if r["name"] == "builder")
    assert row["kind"] == "ai" and "model" in row["ai"]
    assert next(r for r in data["steps"] if r["kind"] != "ai")["ai"] is None
    assert sorted(p.name for p in folder.iterdir()) == before and (folder / "phoenix.toml").read_text() == toml_before


def test_plan_resolve_error_in_errors_not_http_error(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/plan", {"overrides": {"steps": {"builder": {"on": False}}}})
    assert status == 200 and body["data"]["errors"] and body["data"]["steps"]
    status, body = post(api, "/api/projects/alpha/plan", {"overrides": {"bogus": 1}})
    assert status == 200 and body["data"]["errors"] and body["data"]["steps"]


def test_defaults_saved_into_phoenix_toml(api):
    folder = make_project("alpha")
    post(api, "/api/projects/alpha/settings", {"set": {"steps.reviewer.on": True}})
    status, _ = post(api, "/api/projects/alpha/defaults",
                     {"overrides": {"preset": "full", "max_tries": 4, "steps": {"verify": {"on": False}}}})
    assert status == 200
    data = settings.load_project(folder)
    assert data["preset"] == "full" and data["max_tries"] == 4
    assert data["steps"]["verify"]["on"] is False and "on" not in data["steps"].get("reviewer", {})
    status, body = post(api, "/api/projects/alpha/defaults", {"overrides": {"preset": "quick", "bad": 1}})
    assert status == 400 and settings.load_project(folder)["preset"] == "full"


# ---- run start ----

def test_run_start_with_spec_freezes_overrides(api):
    folder = make_project("alpha")
    rel = add_spec(folder)
    status, body = post(api, "/api/projects/alpha/runs", {"spec": rel, "overrides": {"max_tries": 2}})
    assert status == 200
    run_dir = runs_core.find_run(body["data"]["run_id"])
    assert json.loads((run_dir / "overrides.json").read_text()) == {"max_tries": 2}


def test_run_start_spec_outside_notes_400(api, tmp_path):
    folder = make_project("alpha")
    (folder / "notes" / "other.md").write_text(SPEC)
    for rel in ("../CLAUDE.md", "other.md", "specs/missing.md", "../../../etc/passwd"):
        status, body = post(api, "/api/projects/alpha/runs", {"spec": rel})
        assert status == 400, rel


def test_run_start_brief_needs_planner_400(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/runs", {"brief": "Make a tool"})
    assert status == 400 and body["message"] == "A brief needs the Planner step on."


def test_run_start_brief_with_planner_queues_run(api):
    make_project("alpha")
    status, body = post(api, "/api/projects/alpha/runs",
                        {"brief": "Make a tool\nthat says hi", "overrides": {"preset": "full"}})
    assert status == 200
    run_dir = runs_core.find_run(body["data"]["run_id"])
    text = (run_dir / "spec.md").read_text()
    assert text.startswith("# Make a tool\n\nProject: alpha\n\n## About\nMake a tool\nthat says hi")
    assert not list(paths.cache().glob("brief-*"))


FREE = """# Recipe box

A small app for keeping family recipes. Text before the first heading.

## Non-negotiable: works offline
Recipes must load with no network → always.

## Stack (recommended)
Use `sqlite` and ```python``` scripts.

## Build order (MVP → full)
1. Add recipes → 2. Search → 3. Share
### Later
Photos.
"""


def test_run_start_free_form_spec_needs_planner(api):
    folder = make_project("alpha")
    rel = add_spec(folder, FREE, name="recipes.md")
    status, body = post(api, "/api/projects/alpha/runs", {"spec": rel})
    assert status == 400 and "Turn the Planner on" in body["message"]
    status, body = post(api, "/api/projects/alpha/runs", {"spec": rel, "overrides": {"preset": "full"}})
    assert status == 200
    run_dir = runs_core.find_run(body["data"]["run_id"])
    assert (run_dir / "spec.md").read_text() == FREE


def test_run_start_brief_with_own_headings_queues_run(api):
    make_project("alpha")
    brief = FREE.replace("# Recipe box\n", "")
    status, body = post(api, "/api/projects/alpha/runs", {"brief": brief, "overrides": {"preset": "full"}})
    assert status == 200
    text = (runs_core.find_run(body["data"]["run_id"]) / "spec.md").read_text()
    assert "## Stack (recommended)" in text and text.startswith("# A small app for keeping family recipes.")


def test_run_start_spec_and_brief_400(api):
    folder = make_project("alpha")
    rel = add_spec(folder)
    assert post(api, "/api/projects/alpha/runs", {"spec": rel, "brief": "x"})[0] == 400
    assert post(api, "/api/projects/alpha/runs", {})[0] == 400


# ---- stop and gates ----

def test_stop_needs_confirm(api):
    folder = make_project("alpha")
    add_spec(folder)
    run_id = runs_ops.start("alpha", folder / "notes/specs/login.md")["run_id"]
    assert post(api, f"/api/runs/alpha/{run_id}/stop", {})[0] == 400
    make_project("beta")
    assert post(api, f"/api/runs/beta/{run_id}/stop", {"confirm": True})[0] == 404
    status, body = post(api, f"/api/runs/alpha/{run_id}/stop", {"confirm": True})
    assert status == 200 and body["data"]["status"] == "stopped"


def test_gate_answer_back_needs_note(api):
    add_spec(make_project("alpha"))
    gate, _ = open_gate()
    status, body = post(api, f"/api/gates/{gate['id']}/answer", {"action": "back", "note": " "})
    assert status == 400 and "note" in body["message"]
    status, body = post(api, f"/api/gates/{gate['id']}/answer", {"action": "back", "note": "fix it"})
    assert status == 200 and body["data"]["who"] == "dashboard"


def test_gate_answer_unknown_action_400(api):
    add_spec(make_project("alpha"))
    gate, _ = open_gate()
    status, body = post(api, f"/api/gates/{gate['id']}/answer", {"action": "explode"})
    assert status == 400 and "not allowed" in body["message"]


def test_gate_answer_twice_409(api):
    add_spec(make_project("alpha"))
    gate, _ = open_gate()
    assert post(api, f"/api/gates/{gate['id']}/answer", {"action": "approve"})[0] == 200
    status, body = post(api, f"/api/gates/{gate['id']}/answer", {"action": "approve"})
    assert status == 409 and "already answered" in body["message"]


# ---- every write is recorded ----

def test_every_write_logs_command_event_with_who_dashboard(api):
    folder = make_project("alpha")
    rel = add_spec(folder)
    calls = [
        ("/api/projects/alpha/edit", {"description": "Other."}),
        ("/api/projects/alpha/keys/save", {"rows": [{"name": "K", "value": "v"}]}),
        ("/api/projects/alpha/keys/reveal", {"name": "K"}),
        ("/api/projects/alpha/keys/remove", {"name": "K"}),
        ("/api/projects/alpha/settings", {"set": {"max_tries": 4}}),
        ("/api/projects/alpha/settings/preset", {"preset": "full"}),
        ("/api/projects/alpha/defaults", {"overrides": {"max_tries": 2}}),
        ("/api/projects/alpha/runs", {"spec": rel}),
    ]
    for path, body in calls:
        seen = len(paths.events().read_text().splitlines()) if paths.events().exists() else 0
        assert post(api, path, body)[0] == 200, path
        new = [json.loads(x) for x in paths.events().read_text().splitlines()[seen:]]
        commands = [e for e in new if e["type"] == "command"]
        assert commands and all(e["data"]["who"] == "dashboard" for e in commands), path
    lines = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert lines and all(x["who"] == "dashboard" for x in lines)
