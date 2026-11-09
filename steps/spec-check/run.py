"""Spec check: stops the run if the spec has problems, otherwise saves it as spec.json."""
from phoenix9 import atomic, spec
from phoenix9.stepctx import StepResult


def planner_on(ctx) -> bool:
    """True when this run's resolved plan has the Planner among its run-start steps."""
    plan = atomic.read_json(ctx.run.folder / "plan.json") or {}
    return "planner" in (plan.get("groups") or {}).get("run-start", [])


def run(ctx):
    """Fail with every problem found in spec.md; else write spec.json.

    The Planner switch alone decides. Planner off: the strict task format. Planner on: any non-empty text
    (within the size limit) is a description it turns into tasks; the Planner's own output is checked strictly.
    A spec that already passes the strict check keeps its tasks; any other is saved as a brief (no tasks)."""
    text = (ctx.run.folder / "spec.md").read_text(encoding="utf-8")
    parsed = spec.parse(text)
    strict = spec.check(text)
    if not planner_on(ctx):
        problems = strict + [spec.NEEDS_PLANNER] if strict else []
    else:
        problems = spec.check_description(text)
    if problems:
        return StepResult("fail", problems)
    brief = bool(strict)
    data = spec.to_json(parsed)
    if brief:
        data.update({"brief": True, "tasks": [], "title": spec.description_title(text, ctx.run.id), "about": text.strip(),
                     "project": ctx.project.name, "preset": parsed.preset if parsed.preset in spec.PRESETS else ""})
    atomic.write_json(ctx.run.folder / "spec.json", data)
    return StepResult("pass")
