"""The Deploy and Preview finish steps, run through the real runner with the test deployer library."""
import shutil
import sys
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import on
from helpers.stepunit import load
from phoenix9 import atomic, deploy, events, gates, paths, settings, state
from phoenix9.library import load_library
from phoenix9.resolve import resolve
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult
from test_attempt_loop import ONE, project, start  # noqa: F401  (project is a fixture)
from test_deploy_runner import Script
from test_step_merge import URL, gh, world  # noqa: F401  (world is a fixture)

REPO = Path(__file__).resolve().parents[1]
MERGED = "abcdef1234567"
MERGE_STEP = dict(level="run", phase="finish", order=30, needs=["worktree"], produces=["merged"])
DEPLOYERS = Path(__file__).parent / "data" / "deployers"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """Scripted steps plus the real Deploy and Preview steps; the test deployers are the deployer library."""
    scripted.reset()
    root = scripted.make_library(tmp_path / "lib", {**scripted.STEPS, "merge": MERGE_STEP})
    for name in ("deploy", "preview"):
        shutil.rmtree(root / "steps" / name, ignore_errors=True)
        shutil.copytree(REPO / "steps" / name, root / "steps" / name, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "deployers").symlink_to(DEPLOYERS)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    on("merge", None, None, StepResult("pass", produces={"merged": MERGED}))
    yield root
    scripted.reset()
    sys.modules.pop("deploy_script", None)


def set_deploy(project, with_="scripted", mode="on-merge", preview=False):
    """Write the project's [deploy] table."""
    (project / "phoenix.toml").write_text(
        f'[deploy]\nwith = "{with_}"\nmode = "{mode}"\npreview = {str(preview).lower()}\n\n'
        '[deploy.settings]\nlive_port = 8080\n')


def go(tmp_path, adapters, lib, script=None):
    """Start a run and drive it once; returns (runner, run_dir, status)."""
    (script or Script()).install()
    runner = Runner(adapters, lib)
    run_dir = start(tmp_path, ONE)
    return runner, run_dir, runner.drive(run_dir)


def lines(run_dir):
    return {x["step"]: x for x in state.load(run_dir)["steps"] if x.get("task") is None}


def things(run_dir):
    return atomic.read_json(run_dir / "things.json", {})


def open_gate(run_dir):
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    return g


def test_deploy_off_and_none_skip(tmp_path, adapters, lib, project):
    set_deploy(project, mode="off")
    _, run_dir, status = go(tmp_path, adapters, lib)
    assert status == "done" and lines(run_dir)["deploy"]["status"] == "skipped"
    assert "off" in lines(run_dir)["deploy"]["note"]
    set_deploy(project, with_="none", mode="on-merge")
    _, run_dir, status = go(tmp_path, adapters, lib)
    assert status == "done" and lines(run_dir)["deploy"]["status"] == "skipped"
    assert deploy.read_records("proj") == []


def test_no_merge_skips_deploy(tmp_path, adapters, lib, project):
    set_deploy(project)
    on("merge", None, None, StepResult("skip", ["No changes to merge"]))
    script = Script()
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "done"
    assert lines(run_dir)["deploy"]["status"] == "skipped" and "nothing merged" in lines(run_dir)["deploy"]["note"]
    assert "deploy" not in script.calls


def test_merge_left_open_in_ask_mode_does_not_deploy(tmp_path, adapters, lib, project):
    set_deploy(project)
    on("merge", None, None, scripted.gate(kind="merge", title="Merge?", why="ask", actions=["approve", "skip", "stop"]))
    script = Script()
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "waiting" and "deploy" not in lines(run_dir) and script.calls == []


def test_on_merge_deploys_and_produces_url(tmp_path, adapters, lib, project):
    set_deploy(project)
    script = Script()
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "done" and "deploy" in script.calls
    assert lines(run_dir)["deploy"]["status"] == "passed"
    assert things(run_dir)["deployed"] == {"url": "https://demo.example", "version": "v2"}
    (record,) = deploy.read_records("proj")
    assert record["ok"] and record["commit"] == MERGED and record["run"] == run_dir.name
    assert any(e["type"] == "deploy.finished" for e in events.tail(paths.events(), 50))


def test_button_mode_opens_deploy_gate_then_deploys_on_deploy_answer(tmp_path, adapters, lib, project):
    set_deploy(project, mode="button")
    script = Script()
    runner, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "waiting" and script.calls == []
    gate = open_gate(run_dir)
    assert gate["kind"] == "deploy" and gate["actions"] == ["deploy", "skip", "stop"]
    assert gate["title"] == "Deploy proj with Scripted scripted?" and MERGED[:7] in gate["why"]
    gates.answer(gate["id"], "deploy")
    assert runner.drive(run_dir) == "done"
    assert "deploy" in script.calls and lines(run_dir)["deploy"]["status"] == "passed"


def test_button_skip_does_not_deploy(tmp_path, adapters, lib, project):
    set_deploy(project, mode="button")
    script = Script()
    runner, run_dir, _ = go(tmp_path, adapters, lib, script)
    gates.answer(open_gate(run_dir)["id"], "skip")
    assert runner.drive(run_dir) == "done"
    assert script.calls == [] and lines(run_dir)["deploy"]["status"] == "skipped"


def test_failed_health_rolls_back_and_escalates(tmp_path, adapters, lib, project):
    set_deploy(project)
    script = Script(health=((False, "site is down"),))
    runner, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "waiting" and "rollback" in script.calls
    gate = open_gate(run_dir)
    assert gate["kind"] == "escalation" and gate["actions"] == ["acknowledged", "skip", "stop"]
    assert gate["flags"] == ["deploy rolled back"] and "site is down" in gate["why"]
    assert any("deploy failed" in m for m in adapters.notify.messages)
    (record,) = deploy.read_records("proj")
    assert record["rolled_back"] is True and not record["ok"]
    gates.answer(gate["id"], "acknowledged")
    assert runner.drive(run_dir) == "failed"
    assert lines(run_dir)["deploy"]["status"] == "failed" and scripted.calls("notify")


class PreviewScript(Script):
    """A Script whose preview can fail."""
    fail_preview = None

    def preview(self, dctx):
        if self.fail_preview:
            raise deploy.DeployError(self.fail_preview)
        return super().preview(dctx)


def test_preview_skips_when_off(tmp_path, adapters, lib, project):
    set_deploy(project, preview=False)
    script = PreviewScript()
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "done" and lines(run_dir)["preview"]["status"] == "skipped"
    assert "preview" not in script.calls
    set_deploy(project, with_="none", preview=True)
    _, run_dir, _ = go(tmp_path, adapters, lib, script)
    assert lines(run_dir)["preview"]["status"] == "skipped"


def test_preview_runs_and_produces_url(tmp_path, adapters, lib, project):
    set_deploy(project, preview=True)
    script = PreviewScript()
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "done" and "preview" in script.calls
    assert things(run_dir)["preview-url"] == "https://prev.example"
    assert scripted.calls("merge")[0]["things"].get("preview-url") == "https://prev.example"


def test_preview_url_added_to_merge_gate_links(world):
    ctx, _, _ = world
    ctx.project.settings["merge"] = "ask"
    ctx.things["preview-url"] = "https://prev.example"
    gh(ctx, ["pr", "create"], out=URL + "\n")
    result = load("merge").run(ctx)
    assert result.status == "gate"
    assert {"label": "Preview", "url": "https://prev.example"} in result.gate["links"]


def test_preview_failure_does_not_block_merge(tmp_path, adapters, lib, project):
    set_deploy(project, preview=True)
    script = PreviewScript()
    script.fail_preview = "build broke"
    _, run_dir, status = go(tmp_path, adapters, lib, script)
    assert status == "done" and lines(run_dir)["preview"]["status"] == "passed"
    assert lines(run_dir)["merge"]["status"] == "passed"
    assert any("preview failed: build broke" in m for m in adapters.notify.messages)
    assert "preview-url" not in things(run_dir)


def test_preview_stopped_after_merge(world, lib):
    ctx, _, _ = world
    (paths.projects() / "proj").mkdir()
    set_deploy(paths.projects() / "proj", preview=True)
    script = PreviewScript()
    script.install()
    record = deploy.run_preview(ctx.adapters, "proj", who="runner", run_id="r", source_dir=ctx.worktree)
    assert record["ok"]
    ctx.things["preview-url"] = record["url"]
    result = load("merge").run(ctx)
    assert result.status == "pass" and "stop_preview" in script.calls
    assert any("preview was at" in r for r in result.reasons)


def test_presets_resolve_with_preview_and_deploy_on_and_off(tmp_path):
    lib = load_library(REPO)
    assert lib.problems == []
    for preset in ("simple", "quick", "full"):
        proj = tmp_path / preset
        proj.mkdir()
        (proj / "phoenix.toml").write_text(f'preset = "{preset}"\n')
        eff = settings.effective(proj, lib)
        plan = resolve(lib, settings.enabled_map(eff))
        finish = plan.groups["run-finish"]
        assert finish.index("preview") < finish.index("merge") < finish.index("deploy") < finish.index("notify")
        off = resolve(lib, {**settings.enabled_map(eff), "preview": False, "deploy": False})
        assert "preview" not in off.groups["run-finish"] and "deploy" not in off.groups["run-finish"]


def test_explain_shows_preview_skips_unless_switched_on(tmp_path):
    lib = load_library(REPO)
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "phoenix.toml").write_text('preset = "simple"\n')
    text = resolve(lib, settings.enabled_map(settings.effective(proj, lib))).explain()
    assert "Preview (preview) (skips unless [deploy] preview = true)" in text
