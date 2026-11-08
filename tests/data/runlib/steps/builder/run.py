"""Scripted test step: does what <run folder>/script.json says for its name (or name:task)."""
import json

from phoenix9 import state
from phoenix9.stepctx import StepResult


def run(ctx):
    """Log the call and return the scripted result (default: pass, producing '<step>:<task>')."""
    script_file = ctx.run.folder / "script.json"
    script = json.loads(script_file.read_text()) if script_file.exists() else {}
    task = ctx.task["number"] if ctx.task else None
    mine = script.get(f"{ctx.step.name}:{task}") or script.get(ctx.step.name) or {}
    with open(ctx.run.folder / "calls.jsonl", "a") as f:
        f.write(json.dumps({"step": ctx.step.name, "task": task, "things": ctx.things}, default=str) + "\n")
    if mine.get("cost"):                  # pretend a Claude session cost this much
        state.update(ctx.run.folder, lambda s: s["usage"].__setitem__(
            "cost_usd", round(s["usage"]["cost_usd"] + mine["cost"], 6)))
    produces = mine.get("produces", {n: f"{ctx.step.name}:{task}" for n in ctx.step.produces})
    return StepResult(mine.get("status", "pass"), mine.get("reasons", []), produces, mine.get("gate"))
