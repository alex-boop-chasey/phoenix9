"""The Planner step and the plan gate: brief in, spec out, Alex approves, the run builds the new tasks."""
import json
import shutil
from pathlib import Path

import pytest

from helpers import scripted
from helpers.stepunit import load, make_ctx, make_work
from phoenix9 import aistep, atomic, events, gates, runs, state
from phoenix9.__main__ import main
from phoenix9.claude import Result
from phoenix9.runner import Runner
from test_step_builder import project  # noqa: F401  (a fixture)

REPO = Path(__file__).resolve().parents[1]
BRIEF = "# Tiny tool\n\nMake a small tool that says hello, and put it online.\n"
PLAN = """# Tiny tool
Project: proj

## About
A small tool.

## Task 1: Say hello
Write hello.py.
Depends on: none
For you: no
Done when:
- `python3 hello.py`

## Task 2: Buy the domain
Buy a domain for the tool.
Depends on: 1
For you: yes
Done when:
- the domain is bought

## Task 3: Add a readme
Write README.md.
Depends on: 1
For you: no
Done when:
- `test -f README.md`
"""
NO_TASKS = "# Tiny tool\n\n## About\nNothing to do.\n"


def make_lib(root) -> Path:
    scripted.make_library(root)
    for name in ("spec-check", "planner"):
        shutil.copytree(REPO / "steps" / name, root / "steps" / name)
    shutil.copytree(REPO / "profiles", root / "profiles")
    (root / "presets" / "quick.toml").write_text('title = "Q"\n[steps.planner]\non = true\n')
    (root / "presets" / "full.toml").write_text('title = "Full"\n[steps.planner]\non = true\n')
    return root


@pytest.fixture
def setup(tmp_path, adapters, project):
    scripted.reset()
    yield lambda: Runner(adapters, make_lib(tmp_path / "lib"))
    scripted.reset()


def start(tmp_path, text=BRIEF, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(text)
    return runs.create_run("proj", f, overrides or None)


def planner(text=PLAN):
    return {"files": {"/out/spec.md": text}, "text": "PLAN DONE"} if text is not None else {"text": "PLAN DONE"}


def open_gate_id(run_dir) -> str:
    return state.load(run_dir)["current"]["gate"]


def planner_prompts(runner) -> list[str]:
    return [c[2]["prompt_file"].read_text() for c in runner.adapters.claude.calls if c[2]["role"] == "planner"]


def unit_ctx(tmp_path, adapters, planner_on):
    work = make_work(tmp_path)
    ctx = make_ctx(tmp_path, adapters, work, "spec-check")
    ctx.task = None
    (ctx.run.folder / "spec.md").write_text(BRIEF)
    groups = {"run-start": ["pick-up", "spec-check"] + (["planner"] if planner_on else [])}
    atomic.write_json(ctx.run.folder / "plan.json", {"groups": groups})
    return ctx


def test_spec_check_lenient_when_planner_on(tmp_path, adapters):
    ctx = unit_ctx(tmp_path, adapters, True)
    assert load("spec-check").run(ctx).status == "pass"
    data = json.loads((ctx.run.folder / "spec.json").read_text())
    assert data["brief"] is True and data["title"] == "Tiny tool" and data["tasks"] == []


def test_spec_check_strict_when_planner_off(tmp_path, adapters):
    ctx = unit_ctx(tmp_path, adapters, False)
    result = load("spec-check").run(ctx)
    assert result.status == "fail" and any("no tasks" in r for r in result.reasons)
    assert not (ctx.run.folder / "spec.json").exists()


def test_planner_prompt_contains_spec_format_and_no_placeholders(tmp_path, adapters, project):
    ctx = unit_ctx(tmp_path, adapters, True)
    ctx.step.name = "planner"
    ctx.answer = {"action": "back", "notes": ["use fewer tasks", "name the files"]}
    values = load("planner").before(ctx)
    text = aistep.render((REPO / "steps" / "planner" / "prompt.md").read_text(),
                         {**values, "spec_title": "Tiny tool"})
    assert "{{" not in text and "PLAN DONE" in text
    assert "## Task 1: <title>" in text and "Depends on: none | 2, 3" in text and "For you: no | yes" in text
    assert "Make a small tool" in text and "python3 -m pytest -q" in text
    assert "1. use fewer tasks\n2. name the files" in text


def test_bad_plan_fails_with_problems(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner(NO_TASKS)]
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "failed"
    row = [x for x in state.load(run_dir)["steps"] if x["step"] == "planner"][0]
    assert row["status"] == "failed" and "no tasks" in row["note"]
    assert not (run_dir / "plan.md").exists()


def test_good_plan_opens_plan_gate(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "waiting"
    gate = json.loads((run_dir / "gates" / f"{open_gate_id(run_dir)}.json").read_text())
    assert gate["kind"] == "plan" and gate["title"] == "Approve the plan for Tiny tool"
    assert gate["why"] == "3 tasks, 1 for you"
    assert gate["links"] == [{"label": "Plan", "url": str(run_dir / "plan.md")}]
    assert gate["actions"] == ["approve", "back", "skip", "stop"]
    assert (run_dir / "plan.md").read_text() == PLAN
    assert json.loads((run_dir / "plan.json").read_text())["groups"]["run-start"][-1] == "planner"
    launch = [c[2] for c in runner.adapters.claude.calls if c[0] == "launch"][0]
    assert launch["workspace_ro"] is True


def test_planner_out_folder_is_handed_to_the_session_user(tmp_path, setup, monkeypatch):
    """Phoenix runs as root; the session runs as uid 1000, so /out must be chowned or the plan can't be written."""
    from phoenix9 import docker
    monkeypatch.setattr(docker.os, "getuid", lambda: 0)
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    chowned = [c[1][0] for c in runner.adapters.docker.calls if c[0] == "chown"]
    assert str((run_dir / "planner-out").resolve()) in [str(type(run_dir)(p).resolve()) for p in chowned]


def test_back_reruns_with_note(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner(), planner()]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    first = planner_prompts(runner)[0]      # the prompt file is rewritten by the second session
    gates.answer(open_gate_id(run_dir), "back", note="split task 1 smaller")
    assert runner.drive(run_dir) == "waiting"
    second = planner_prompts(runner)[-1]
    assert "split task 1 smaller" not in first and "1. split task 1 smaller" in second
    assert len([g for g in (run_dir / "gates").glob("*.json") if not g.name.endswith(".answer.json")]) == 2


def test_approve_adopts_plan_tasks(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    assert list(state.load(run_dir)["tasks"]) == []
    gates.answer(open_gate_id(run_dir), "approve")
    runner.drive(run_dir)
    st = state.load(run_dir)
    assert sorted(st["tasks"]) == ["1", "2", "3"] and st["tasks"]["3"]["depends_on"] == [1]
    assert st["tasks"]["2"]["status"] == "waiting"           # the For-you task opened its own gate
    assert [c["task"] for c in scripted.calls("builder")] == [1]
    gates.answer(st["tasks"]["2"]["gate"], "approve")
    runner.drive(run_dir)
    assert [c["task"] for c in scripted.calls("builder")] == [1, 3]
    assert state.load(run_dir)["status"] == "done"
    done = [e for e in events.read(run_dir / "events.jsonl")
            if e["type"] == "run.step.finished" and e["step"] == "planner"]
    assert done[-1]["data"]["plan_adopted"] is True
    assert json.loads((run_dir / "spec.json").read_text())["tasks"][1]["title"] == "Buy the domain"


def test_skip_with_no_tasks_fails_run(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    gates.answer(open_gate_id(run_dir), "skip")
    assert runner.drive(run_dir) == "failed"
    last = events.read(run_dir / "events.jsonl")[-1]
    assert last["type"] == "run.finished"
    assert last["data"]["reason"] == "No plan: the brief has no tasks and the plan was skipped"
    assert not scripted.calls("builder")


def test_skip_with_brief_tasks_uses_brief(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    brief = "# Tiny tool\n\n## Task 1: Only\nDo it.\nDone when:\n- `true`\n"
    run_dir = start(tmp_path, brief)
    assert runner.drive(run_dir) == "waiting", [x["note"] for x in state.load(run_dir)["steps"]]
    gates.answer(open_gate_id(run_dir), "skip")
    assert runner.drive(run_dir) == "done"
    assert list(state.load(run_dir)["tasks"]) == ["1"]


def test_full_preset_plan_gate_end_to_end(tmp_path, setup, capsys):
    runner = setup()
    runner.adapters.claude.sessions += [planner()]
    run_dir = start(tmp_path, preset="full")
    assert runner.drive(run_dir) == "waiting"
    assert main(["gate", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [g["kind"] for g in listed] == ["plan"] and listed[0]["run"] == run_dir.name
    assert main(["gate", "answer", listed[0]["id"], "approve"]) == 0
    capsys.readouterr()
    runner.drive(run_dir)
    st = state.load(run_dir)
    assert st["tasks"]["1"]["status"] == "passed" and st["tasks"]["2"]["status"] == "waiting"
    gates.answer(st["tasks"]["2"]["gate"], "approve")
    assert runner.drive(run_dir) == "done"
    assert state.load(run_dir)["tasks"]["3"]["status"] == "passed"
