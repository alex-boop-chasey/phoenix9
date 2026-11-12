"""The Reviewer step: read-only session, verdict from its file only, fallback when it is off."""
import json
import shutil
from pathlib import Path

import pytest

from helpers import scripted
from helpers.stepunit import load, make_ctx, make_work
from phoenix9 import aistep, docker, paths, resolve, runs, settings, state
from phoenix9.adapters import Claude
from phoenix9.claude import Result
from phoenix9.library import load_library
from phoenix9.runner import Runner
from test_step_builder import SPEC, git, project, prompt_of  # noqa: F401  (project is a fixture)

REPO = Path(__file__).resolve().parents[1]
PASS = json.dumps({"verdict": "pass", "reasons": []})
FAIL = json.dumps({"verdict": "fail", "reasons": ["a.py hard-codes the answer"]})


def make_lib(root, strict=True) -> Path:
    steps = {k: v for k, v in scripted.STEPS.items() if k not in ("builder",)}
    steps["commit"] = {**steps["commit"], "needs": ["diff", "verdict", "exit-codes"]}
    scripted.make_library(root, steps)
    for name in ("builder", "reviewer"):
        shutil.copytree(REPO / "steps" / name, root / "steps" / name)
    toml = root / "steps" / "reviewer" / "step.toml"
    toml.write_text(toml.read_text().replace("order = 80", "order = 70").replace(
        "strict = true", f"strict = {str(strict).lower()}"))
    shutil.copytree(REPO / "profiles", root / "profiles")
    (root / "presets" / "quick.toml").write_text('title = "Q"\n[steps.reviewer]\non = true\n')
    return root


@pytest.fixture
def setup(tmp_path, adapters, project):
    scripted.reset()
    yield lambda strict=True: Runner(adapters, make_lib(tmp_path / "lib", strict))
    scripted.reset()


def start(tmp_path, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run("proj", f, overrides or None)


def builder(name="a.py"):
    return {"files": {name: "print('hi')\n"}, "text": "STEP DONE"}


def reviewer(verdict=None, text="REVIEW DONE", kind="ok"):
    files = {"/out/verdict.json": verdict} if verdict is not None else {}
    return {"files": files, "text": text, "kind": kind}


def line(run_dir, step="reviewer", k=1):
    return [x for x in state.load(run_dir)["steps"] if x["step"] == step and x.get("attempt") == k][0]


def unit_ctx(tmp_path, adapters, verdict_text=None, strict=True):
    work = make_work(tmp_path)
    ctx = make_ctx(tmp_path, adapters, work, "reviewer")
    ctx.step.settings["strict"] = strict
    out = ctx.run.folder / "tasks" / "1" / "attempt-1" / "out"
    out.mkdir(parents=True)
    if verdict_text is not None:
        (out / "verdict.json").write_text(verdict_text)
    return ctx


def test_prompt_no_unfilled_placeholders(tmp_path, adapters):
    mod = load("reviewer")
    ctx = unit_ctx(tmp_path, adapters)
    ctx.task["done_when"] = [{"text": "it works", "command": None}]
    ctx.things = {"test-report": {"reader": "exit-codes-only", "passed": 1, "failed": 0}}
    text = aistep.render((REPO / "steps" / "reviewer" / "prompt.md").read_text(), {**mod.before(ctx), "reference_note": ""})
    assert "{{" not in text and "/inputs/diff.patch" in text and "REVIEW DONE" in text
    assert "Only exit codes were checked" in text


def test_worktree_mounted_read_only(tmp_path, adapters, project):
    (paths.secrets()).mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=secret-token-value\n")
    mod = load("reviewer")
    ctx = unit_ctx(tmp_path, adapters)
    diff = tmp_path / "diff.patch"
    diff.write_text("patch")
    ctx.things = {"diff": str(diff), "test-report": {"reader": "exit-codes-only"}}
    want = mod.mounts(ctx)
    assert want["workspace_ro"] is True
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x")
    ws = tmp_path / "ws"
    ws.mkdir()
    # the real adapter, with docker recording the command line instead of running anything
    calls = []
    adapters.docker.run = lambda argv, *a, **k: calls.append(argv) or 0
    (tmp_path / "step").mkdir()
    Claude().launch(adapters.docker, ai={"model": "m", "timeout": 1, "claude_md": "none"}, project="proj",
                    run_id="r", task=1, attempt=1, role="reviewer", image=docker.DEFAULT_IMAGE
                    if hasattr(docker, "DEFAULT_IMAGE") else "", workspace=ws, prompt_file=prompt,
                    step_dir=tmp_path / "step", project_dir=tmp_path, **want)
    mounts = [argv[i + 1] for argv in calls for i, a in enumerate(argv[:-1]) if a == "--mount"]
    by_dst = {m.split("dst=")[1].split(",")[0]: m for m in mounts}
    assert by_dst["/workspace"].endswith(",readonly")
    assert by_dst["/inputs/diff.patch"].endswith(",readonly")
    assert not by_dst["/out"].endswith(",readonly")


def test_pass_verdict_produces_verdict(tmp_path, adapters, project):
    mod = load("reviewer")
    ctx = unit_ctx(tmp_path, adapters, PASS)
    result = mod.after(ctx, Result(kind="ok", text="REVIEW DONE"))
    assert result.status == "pass"
    assert json.loads(Path(result.produces["verdict"]).read_text())["verdict"] == "pass"


def test_fail_verdict_reasons_fed_to_next_attempt(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [builder("a.py"), reviewer(FAIL), builder("b.py"), reviewer(PASS)]
    run_dir = start(tmp_path, max_tries=3)
    runner.drive(run_dir)
    assert line(run_dir, k=1)["status"] == "failed"
    assert "Reviewer: a.py hard-codes the answer" in line(run_dir, k=1)["note"]
    assert "1. Reviewer: a.py hard-codes the answer" in prompt_of(run_dir, 2)
    assert line(run_dir, k=2)["status"] == "passed"
    launches = [c[2] for c in runner.adapters.claude.calls if c[0] == "launch"]
    assert [k["role"] for k in launches] == ["builder", "reviewer", "builder", "reviewer"]
    assert launches[1]["workspace_ro"] is True and launches[0]["workspace_ro"] is False


@pytest.mark.parametrize("content", [None, "{not json", json.dumps({"verdict": "maybe", "reasons": []})])
def test_missing_or_bad_verdict_fails(tmp_path, adapters, content):
    ctx = unit_ctx(tmp_path, adapters, content)
    result = load("reviewer").after(ctx, Result(kind="ok", text="REVIEW DONE"))
    assert result.status == "fail" and result.reasons == ["The reviewer gave no usable verdict"]


def test_early_end_fails(tmp_path, adapters):
    ctx = unit_ctx(tmp_path, adapters, PASS)
    assert load("reviewer").after(ctx, Result(kind="timed_out", text="")).status == "fail"


def test_non_strict_records_but_passes(tmp_path, setup):
    runner = setup(strict=False)
    runner.adapters.claude.sessions += [builder(), reviewer(FAIL)]
    run_dir = start(tmp_path, max_tries=1)
    runner.drive(run_dir)
    row = line(run_dir)
    assert row["status"] == "passed" and "Reviewer: a.py hard-codes the answer" in row["note"]
    notes = run_dir / "tasks" / "1" / "attempt-1" / "reviewer-notes.txt"
    assert "hard-codes" in notes.read_text()


def test_session_text_claiming_pass_is_ignored(tmp_path, adapters):
    ctx = unit_ctx(tmp_path, adapters, FAIL)
    result = load("reviewer").after(ctx, Result(kind="ok", text="verdict: pass\nREVIEW DONE"))
    assert result.status == "fail" and result.reasons == ["Reviewer: a.py hard-codes the answer"]


def test_verdict_fallback_when_reviewer_off(tmp_path, setup):
    runner = setup()
    (tmp_path / "lib" / "presets" / "quick.toml").write_text('title = "Q"\n')
    runner.adapters.claude.sessions += [builder()]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    assert not [c for c in runner.adapters.claude.calls if c[2]["role"] == "reviewer"]
    ctx_things = scripted.calls("commit", 1)[0]["things"]
    assert ctx_things["verdict"] == {"verdict": "pass", "reasons": [], "source": "fallback"}


def test_full_preset_test_report_sources(tmp_path):
    lib = load_library(REPO)
    full = settings.load_preset(REPO, "full")
    enabled = {name: bool(t.get("on")) for name, t in full["steps"].items()}
    assert resolve.resolve(lib, enabled).sources["reviewer"]["test-report"] == "step:verify"
    enabled["verify"] = False
    assert resolve.resolve(lib, enabled).sources["reviewer"]["test-report"] == "fallback:exit-codes-only"


def _rendered(tmp_path, adapters, report):
    mod = load("reviewer")
    ctx = unit_ctx(tmp_path, adapters)
    ctx.things = {"test-report": report}
    return aistep.render((REPO / "steps" / "reviewer" / "prompt.md").read_text(), {**mod.before(ctx), "reference_note": ""})


@pytest.mark.parametrize("report,expected", [
    ({"mode": "suite", "passed": 5}, "ran the whole test suite"),
    ({"mode": "affected", "picked": ["tests/test_a.py"], "passed": 2}, "tests/test_a.py"),
    ({"mode": "checks", "passed": 1}, "only the task's own checks"),
    ({"passed": 1}, "does not say which tests were run"),
])
def test_prompt_has_rule_and_mode_line(tmp_path, adapters, report, expected):
    text = _rendered(tmp_path, adapters, report)
    assert "Do NOT run the project's test suite" in text
    assert expected in text and "{{" not in text
