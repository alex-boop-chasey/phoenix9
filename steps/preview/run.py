"""Preview: puts the run's branch on a temporary address before Merge (never blocks the merge)."""
from phoenix9 import deploy as deploylib
from phoenix9.stepctx import StepResult


def _wanted(ctx) -> str:
    """'' when a preview should run, else the plain reason it will not."""
    cfg = ctx.project.settings.get("deploy") or {}
    if not cfg.get("preview", False):
        return "preview is off for this project"
    name = cfg.get("with", "none")
    if name == "none":
        return "the project has no deployer"
    found = deploylib.get(name)
    if found is None or not found["supported"] or not found["preview"]:
        return f"{found['title'] if found else name} cannot deploy a preview"
    return ""


def run(ctx):
    """Deploy the run's worktree as a preview; a failure is noted and the run goes on."""
    why = _wanted(ctx)
    if why:
        return StepResult("skip", [why])
    record = deploylib.run_preview(ctx.adapters, ctx.project.name, who="runner", run_id=ctx.run.id,
                                   source_dir=ctx.worktree)
    if record.get("ok") and record.get("url"):
        return StepResult("pass", [f"preview at {record['url']}"], produces={"preview-url": record["url"]})
    reason = record.get("reason") or record.get("skipped") or "no address came back"
    ctx.log(f"preview failed: {reason}")
    ctx.adapters.notify.send(f"{ctx.project.name}: preview failed: {reason}")
    return StepResult("pass", [f"preview failed: {reason}"])
