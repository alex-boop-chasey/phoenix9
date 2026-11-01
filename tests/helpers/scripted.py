"""A scripted step library for runner tests.

`make_library(root)` writes a small step library (step.toml + a two-line run.py per step) whose steps
all answer through `respond(ctx)`. A test scripts what each call returns with `on(step, task, attempt,
*answers)` and reads back every call from `CALLS`.

An answer is a StepResult, an Exception (raised, i.e. the step crashes), or a function `f(ctx)` that
returns a StepResult. Several answers for one key are used one per call (the last one repeats).
Keys are looked up most specific first: (step, task, attempt), (step, task, any), (step, any, any).
Unscripted calls pass and produce "<step>:<task>" for each thing the step produces.

The default library (names, levels, orders):
  run-start: pick-up 10, branch 40 (makes the run's real git worktree when code/ is a git repo)
  task:      checks 10 (settings once = true, produces checks), builder 30, acceptance 60, commit 80
  run-finish: summary 20, notify 50 (settings after_stop = true)
"""
from __future__ import annotations

from pathlib import Path

from phoenix9 import paths
from phoenix9.stepctx import StepResult

REPO = Path(__file__).resolve().parents[2]
CALLS: list[dict] = []
SCRIPT: dict[tuple, list] = {}

STEPS = {
    "pick-up": dict(level="run", phase="start", order=10, needs=["spec"], produces=[]),
    "branch": dict(level="run", phase="start", order=40, needs=["spec"], produces=["baseline"]),
    "checks": dict(level="task", order=10, needs=["task", "worktree"], produces=["checks"],
                   settings={"once": True}),
    "builder": dict(level="task", order=30, needs=["task", "worktree", "failures", "checks"], produces=["diff"]),
    "acceptance": dict(level="task", order=60, needs=["diff"], produces=["exit-codes"]),
    "commit": dict(level="task", order=80, needs=["diff", "exit-codes"], produces=["commit"]),
    "summary": dict(level="run", phase="finish", order=20, needs=["commit"], produces=[]),
    "notify": dict(level="run", phase="finish", order=50, needs=["spec"], produces=[],
                   settings={"after_stop": True}),
}
RUN_PY = "from helpers.scripted import respond\n\n\ndef run(ctx):\n    return respond(ctx)\n"


def _toml_list(items) -> str:
    return "[" + ", ".join(f'"{x}"' for x in items) + "]"


def make_library(root, steps: dict | None = None) -> Path:
    """Write the scripted library into root (steps/, presets/quick.toml) and return root."""
    root = Path(root)
    sdir = root / "steps"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "_things.toml").write_text((REPO / "steps" / "_things.toml").read_text())
    for name, d in (steps or STEPS).items():
        folder = sdir / name
        folder.mkdir(exist_ok=True)
        lines = [f'name = "{name}"', f'title = "{name}"', 'kind = "script"', f'level = "{d["level"]}"',
                 f'phase = "{d.get("phase", "")}"', f'order = {d["order"]}', f'needs = {_toml_list(d["needs"])}',
                 f'produces = {_toml_list(d["produces"])}', 'default = "always"']
        if d.get("settings"):
            lines += ["", "[settings]"] + [f"{k} = {str(v).lower() if isinstance(v, bool) else repr(v)}"
                                           for k, v in d["settings"].items()]
        (folder / "step.toml").write_text("\n".join(lines) + "\n")
        (folder / "run.py").write_text(RUN_PY)
    (root / "presets").mkdir(exist_ok=True)
    (root / "presets" / "quick.toml").write_text('title = "Quick (scripted)"\n')
    return root


def reset() -> None:
    """Forget every script and call (each test starts clean)."""
    CALLS.clear()
    SCRIPT.clear()


def on(step: str, task: int | None = None, attempt: int | None = None, *answers) -> None:
    """Script what a step returns for (task, attempt); None means any."""
    SCRIPT[(step, task, attempt)] = list(answers)


def fail(*reasons) -> StepResult:
    """A failed step with these reasons."""
    return StepResult("fail", list(reasons))


def gate(**spec) -> StepResult:
    """A step asking for a gate."""
    produces = spec.pop("produces", {})
    return StepResult("gate", gate=spec, produces=produces)


def calls(step: str | None = None, task: int | None = None) -> list[dict]:
    """The recorded calls, optionally for one step and/or task."""
    return [c for c in CALLS if (step is None or c["step"] == step) and (task is None or c["task"] == task)]


def _make_worktree(ctx) -> None:
    code = ctx.project.code_dir
    work = paths.work(ctx.project.name, ctx.run.id)
    if (code / ".git").exists() and not work.exists():
        ctx.adapters.git.make_worktree(code, ctx.run.id, work)


def respond(ctx) -> StepResult:
    """Record the call and return the scripted answer for (step, task, attempt)."""
    task = ctx.task["number"] if ctx.task else None
    name = ctx.step.name
    CALLS.append({"step": name, "task": task, "attempt": ctx.attempt, "answer": ctx.answer,
                  "failures": list(ctx.things.get("failures") or []), "things": dict(ctx.things),
                  "worktree": ctx.worktree})
    if name == "branch":
        _make_worktree(ctx)
    for key in ((name, task, ctx.attempt), (name, task, None), (name, None, None)):
        if key in SCRIPT and SCRIPT[key]:
            answers = SCRIPT[key]
            answer = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(answer, BaseException):
                raise answer
            if callable(answer):
                answer = answer(ctx)
            return answer
    return StepResult("pass", produces={n: f"{name}:{task}" for n in ctx.step.produces})
