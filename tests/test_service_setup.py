"""Service setup: keys, hosts, recipes and notes, through the real runner with fakes."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from phoenix9 import gates, keys, paths, project, runs, services, settings, state
from phoenix9.library import load_library
from phoenix9.ops import common
from phoenix9.ops import services as ops_services
from phoenix9.resolve import resolve
from phoenix9.runner import Runner

REPO = Path(__file__).resolve().parent.parent
SPEC = "# Spec: Setup test\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it is done fine\n"
SENTINEL = "SENTINEL-KEY-VALUE-123"
SETUP_STEPS = {k: v for k, v in scripted.STEPS.items() if k in ("pick-up", "branch", "builder")}


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_project(name="proj", services='["supabase"]', extra=""):
    folder = paths.projects() / name
    code = folder / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    (folder / "phoenix.toml").write_text(f"services = {services}\n{extra}")
    (folder / ".phoenix").mkdir()
    (folder / ".phoenix" / "project.json").write_text(json.dumps({"repo": "", "services_set_up": []}))
    return folder


def make_lib(root, builder_real=False):
    steps = {k: v for k, v in SETUP_STEPS.items() if builder_real is False or k != "builder"}
    scripted.make_library(root, steps)
    shutil.copytree(REPO / "steps" / "service-setup", root / "steps" / "service-setup")
    shutil.copytree(REPO / "services", root / "services")
    if builder_real:
        shutil.copytree(REPO / "steps" / "builder", root / "steps" / "builder")
        shutil.copytree(REPO / "profiles", root / "profiles")
    return root


@pytest.fixture(autouse=True)
def clean_script():
    scripted.reset()
    yield
    scripted.reset()


def new_run(tmp_path, project_name="proj"):
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run(project_name, f, {"max_tries": 1, "on_failure": "continue"})


def step_line(run_dir, name="service-setup"):
    return [x for x in state.load(run_dir)["steps"] if x["step"] == name][0]


def open_gate(run_dir):
    return gates.read(run_dir, state.load(run_dir)["current"]["gate"])


def paste_all(name="proj"):
    """Give every key the chosen services expect a value (rows are added first, as set_services does)."""
    lib = services.load_library()
    for svc in settings.load_project(paths.projects() / name).get("services", []):
        for k in lib[svc]["project_keys"]:
            keys.set_key(name, k["name"], SENTINEL, secret=k["secret"])


def test_no_services_passes_with_fallback(tmp_path, adapters):
    make_project(services="[]")
    run_dir = new_run(tmp_path)
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "done"
    line = step_line(run_dir)
    assert line["status"] == "passed"
    assert json.loads((run_dir / "things.json").read_text())["service-notes"] == "This project uses no third-party services."


def test_missing_keys_open_human_task_gate_listing_names(tmp_path, adapters):
    make_project()
    keys.add_empty("proj", "SUPABASE_URL", False)
    run_dir = new_run(tmp_path)
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "waiting"
    gate = open_gate(run_dir)
    assert gate["kind"] == "human-task" and gate["actions"] == ["done", "skip", "stop"]
    assert gate["title"] == "Paste keys for Supabase"
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        assert name in gate["why"]
    assert "phoenix project keys proj set KEY" in gate["why"]
    assert SENTINEL not in json.dumps(gate)


def test_done_after_keys_pasted_passes(tmp_path, adapters):
    make_project()
    run_dir = new_run(tmp_path)
    runner = Runner(adapters, make_lib(tmp_path / "lib"))
    assert runner.drive(run_dir) == "waiting"
    paste_all()
    gates.answer(open_gate(run_dir)["id"], "done")
    assert runner.drive(run_dir) == "done"
    assert step_line(run_dir)["status"] == "passed"
    notes = (run_dir / "services.md").read_text()
    assert "Supabase" in notes and "SUPABASE_URL" in notes and SENTINEL not in notes


def test_done_without_keys_fails_naming_them(tmp_path, adapters):
    make_project()
    run_dir = new_run(tmp_path)
    runner = Runner(adapters, make_lib(tmp_path / "lib"))
    runner.drive(run_dir)
    keys.set_key("proj", "SUPABASE_URL", SENTINEL, secret=False)
    gates.answer(open_gate(run_dir)["id"], "done")
    assert runner.drive(run_dir) == "failed"
    line = step_line(run_dir)
    assert line["status"] == "failed"
    assert "SUPABASE_ANON_KEY" in line["note"] and "SUPABASE_SERVICE_ROLE_KEY" in line["note"]
    assert "SUPABASE_URL" not in line["note"]


def test_skip_continues_the_run(tmp_path, adapters):
    make_project()
    run_dir = new_run(tmp_path)
    runner = Runner(adapters, make_lib(tmp_path / "lib"))
    runner.drive(run_dir)
    gates.answer(open_gate(run_dir)["id"], "skip")
    assert runner.drive(run_dir) == "done"
    assert step_line(run_dir)["status"] == "skipped"
    assert scripted.calls("builder")


def test_done_recorded_and_skipped_next_run(tmp_path, adapters):
    folder = make_project()
    paste_all()
    lib = make_lib(tmp_path / "lib")
    (lib / "services" / "supabase" / "recipe.py").write_text(
        "CALLS = []\n\n\ndef wire(ctx, service, proxy):\n"
        "    (ctx.run.folder.parent / 'recipe-calls.txt').open('a').write('x')\n    return {'ok': True}\n")
    monkey_lib = lib
    import os
    os.environ["PHOENIX_LIBRARY"] = str(monkey_lib)
    try:
        first = new_run(tmp_path)
        assert Runner(adapters, lib).drive(first) == "done"
        entries = project._meta(folder)["services_set_up"]
        assert entries[0]["name"] == "supabase" and entries[0]["run"] == first.name and entries[0]["at"]
        assert entries[0]["run_name"]
        shown = project.setup_facts(folder)["services_set_up"]
        assert shown[0]["name"] == "supabase" and shown[0]["run_name"] == entries[0]["run_name"]
        second = new_run(tmp_path)
        assert Runner(adapters, lib).drive(second) == "done"
    finally:
        del os.environ["PHOENIX_LIBRARY"]
    assert (first.parent / "recipe-calls.txt").read_text() == "x"      # recipe ran once only
    assert len(project._meta(folder)["services_set_up"]) == 1
    assert "Supabase" in (second / "services.md").read_text()


def test_plain_string_entries_still_count(tmp_path, adapters):
    folder = make_project()
    project._save_meta(folder, services_set_up=["supabase"])
    paste_all()
    run_dir = new_run(tmp_path)
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "done"
    assert project._meta(folder)["services_set_up"] == ["supabase"]


def test_missing_hosts_added_to_project_domains_allow(tmp_path, adapters):
    folder = make_project()
    paste_all()
    run_dir = new_run(tmp_path)
    seen = {}
    scripted.on("builder", None, None, lambda ctx: seen.update(allow=list(ctx.project.settings["domains"]["allow"]))
                or scripted.StepResult("pass", produces={"diff": "x"}))
    assert settings.load_project(folder).get("domains", {}).get("allow", []) == []
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "done"
    assert "supabase.co" in settings.load_project(folder)["domains"]["allow"]
    assert "supabase.co" in seen["allow"]
    assert "added to the project's allowed hosts" in (run_dir / "logs" / "service-setup.log").read_text()


def test_github_recipe_checks_repo_through_proxy(tmp_path, adapters, monkeypatch):
    folder = make_project(services='["github"]')
    project._save_meta(folder, repo="alex/thing")
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", "http://proxy.fake/github/user", 200, body=b"{}")
    ops_services.connect("github", {"GH_TOKEN": SENTINEL}, who="test")
    adapters.proxy.started.clear()
    adapters.proxy.stopped.clear()
    adapters.http.script("GET", "http://proxy.fake/github/repos/alex/thing", 200, body=b"{}")
    lib = make_lib(tmp_path / "lib")
    run_dir = new_run(tmp_path)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    started = [s for s in adapters.proxy.started if s["step"] == "service-setup"]
    assert [s["service"] for s in started] == ["github"]
    assert any(r.path == "/repos/*/*" for r in started[0]["rules"])
    assert adapters.proxy.running() == []
    call = [c for c in adapters.http.calls if c["url"].endswith("/repos/alex/thing")][0]
    assert call["headers"]["X-Phoenix-Proxy-Token"] == adapters.proxy.TOKEN
    # a 404 fails with the plain reason
    project._save_meta(folder, services_set_up=[], repo="alex/gone")
    second = new_run(tmp_path)
    assert Runner(adapters, lib).drive(second) == "failed"
    assert "GitHub repo alex/gone not found or not visible" in step_line(second)["note"]
    assert adapters.proxy.running() == []


def test_github_recipe_without_proxy_is_ok(tmp_path, adapters):
    folder = make_project(services='["github"]')
    project._save_meta(folder, repo="alex/thing")
    run_dir = new_run(tmp_path)
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "done"
    assert not [c for c in adapters.http.calls if "repos" in c["url"]]


def test_unknown_service_fails(tmp_path, adapters):
    make_project(services='["nonesuch"]')
    run_dir = new_run(tmp_path)
    assert Runner(adapters, make_lib(tmp_path / "lib")).drive(run_dir) == "failed"
    assert step_line(run_dir)["note"] == "Service nonesuch is not in Phoenix's services library"


def test_builder_prompt_contains_service_notes_without_values(tmp_path, adapters):
    make_project()
    paste_all()
    adapters.claude.sessions += [{"files": {"a.py": "x\n"}, "text": "STEP DONE"}]
    run_dir = new_run(tmp_path)
    Runner(adapters, make_lib(tmp_path / "lib", builder_real=True)).drive(run_dir)
    prompt = (run_dir / "tasks" / "1" / "attempt-1" / "builder-prompt.md").read_text()
    assert "## Services this project uses" in prompt and "SUPABASE_SERVICE_ROLE_KEY" in prompt
    assert "@supabase/supabase-js" in prompt and SENTINEL not in prompt and "{{" not in prompt


def test_builder_prompt_without_services_says_so(tmp_path, adapters):
    make_project(services="[]")
    adapters.claude.sessions += [{"files": {"a.py": "x\n"}, "text": "STEP DONE"}]
    run_dir = new_run(tmp_path)
    Runner(adapters, make_lib(tmp_path / "lib", builder_real=True)).drive(run_dir)
    prompt = (run_dir / "tasks" / "1" / "attempt-1" / "builder-prompt.md").read_text()
    assert "This project uses no third-party services." in prompt


@pytest.mark.parametrize("preset", ["simple", "quick", "full"])
@pytest.mark.parametrize("on", [True, False])
def test_presets_still_resolve(tmp_path, preset, on):
    lib = load_library(REPO)
    proj = tmp_path / f"p-{preset}-{on}"
    proj.mkdir()
    (proj / "phoenix.toml").write_text(f'preset = "{preset}"\n[steps.service-setup]\non = {str(on).lower()}\n')
    plan = resolve(lib, settings.enabled_map(settings.effective(proj, lib)))
    starts = plan.groups["run-start"]
    assert ("service-setup" in starts) is on
    if on:
        assert starts.index("service-setup") > starts.index("branch")
        assert starts.index("service-setup") == len(starts) - 1
        assert plan.sources["builder"]["service-notes"] == "step:service-setup"
    else:
        assert plan.sources["builder"]["service-notes"] == "fallback:no-services"


def test_setup_facts_reads_old_string_entries(tmp_path):
    folder = make_project()
    project._save_meta(folder, services_set_up=["supabase"])
    assert project.setup_facts(folder)["services_set_up"] == [
        {"name": "supabase", "at": None, "run": None, "run_name": None}]
