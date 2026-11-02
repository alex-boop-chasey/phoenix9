"""Spec check: stops the run if the spec has problems, otherwise saves it as spec.json."""
from phoenix9 import atomic, spec
from phoenix9.stepctx import StepResult


def planner_on(ctx) -> bool:
    """True when this run's resolved plan has the Planner among its run-start steps."""
    plan = atomic.read_json(ctx.run.folder / "plan.json") or {}
    return "planner" in (plan.get("groups") or {}).get("run-start", [])


def run(ctx):
    """Fail with every problem found in spec.md; else write spec.json. With the Planner on, a brief (a title and no tasks) is fine."""
    text = (ctx.run.folder / "spec.md").read_text(encoding="utf-8")
    parsed = spec.parse(text)
    brief = planner_on(ctx) and not parsed.tasks     # a brief has no tasks yet; one with tasks is checked strictly
    if brief:
        problems = [] if parsed.title else ["Line 1: the spec must start with '# <title>'."]
    else:
        problems = spec.check(text)
    if problems:
        return StepResult("fail", problems)
    data = spec.to_json(parsed)
    if brief:
        data["brief"] = True
    atomic.write_json(ctx.run.folder / "spec.json", data)
    return StepResult("pass")
