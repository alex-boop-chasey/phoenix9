"""Spec check: stops the run if the spec has problems, otherwise saves it as spec.json."""
from phoenix9 import atomic, spec
from phoenix9.stepctx import StepResult


def run(ctx):
    """Fail with every problem found in spec.md; else write spec.json."""
    text = (ctx.run.folder / "spec.md").read_text(encoding="utf-8")
    problems = spec.check(text)
    if problems:
        return StepResult("fail", problems)
    atomic.write_json(ctx.run.folder / "spec.json", spec.to_json(spec.parse(text)))
    return StepResult("pass")
