"""Deploy: after a merge, puts the merged code live with the project's deployer (on-merge, or after a button press)."""
from phoenix9 import deploy as deploylib
from phoenix9.stepctx import StepResult

NOT_MERGED = ("", "not-merged", None)


def _settings(ctx) -> dict:
    """The project's [deploy] table as frozen for this run."""
    return ctx.project.settings.get("deploy") or {}


def _stop_preview(ctx) -> None:
    """Nothing merged: stop this run's preview, if there is one (best effort)."""
    if str(ctx.things.get("preview-url") or "").startswith("http"):
        ctx.log(deploylib.try_stop_preview(ctx.adapters, ctx.project.name, ctx.run.id))


def _title(name: str) -> str:
    """The deployer's title, or its name when the library does not know it."""
    found = deploylib.get(name)
    return found["title"] if found else name


def _button_gate(ctx, merged: str, name: str) -> StepResult:
    """Ask Alex whether to deploy now."""
    gate = {"kind": "deploy", "title": f"Deploy {ctx.project.name} with {_title(name)}?",
            "why": f"merged commit {merged[:7]}; target: {_title(name)}", "links": [],
            "actions": ["deploy", "skip", "stop"], "flags": []}
    return StepResult("gate", gate=gate)


def _escalation(ctx, record: dict) -> StepResult:
    """A failed deploy: tell Alex what happened and what the site is doing now."""
    reason = record.get("reason") or "no reason given"
    if record.get("rolled_back"):
        back = f"rolled back to {(record.get('version') or 'the last good deploy')} (healthy)"
    else:
        back = "rollback could not restore the site"
    ctx.adapters.notify.send(f"{ctx.project.name}: deploy failed: {reason}; {back}")
    gate = {"kind": "escalation", "title": f"Deploy of {ctx.project.name} failed", "why": f"deploy failed: {reason}; {back}",
            "links": [], "actions": ["acknowledged", "skip", "stop"], "flags": ["deploy rolled back"]}
    return StepResult("gate", gate=gate)


def _deploy(ctx, merged: str) -> StepResult:
    """Deploy the merged commit through the deployers runner."""
    record = deploylib.run_deploy(ctx.adapters, ctx.project.name, run_id=ctx.run.id, commit=merged, who="runner")
    if record.get("skipped"):
        return StepResult("skip", [f"nothing to do: {record['skipped']}"])
    if record.get("ok"):
        return StepResult("pass", [f"deployed to {record.get('url') or 'the live site'}"],
                          produces={"deployed": {"url": record.get("url", ""), "version": record.get("version", "")}})
    if "rolled_back" not in record:        # refused before anything ran (unknown deployer, bad settings)
        return StepResult("fail", [f"deploy failed: {record.get('reason', 'unknown')}"])
    return _escalation(ctx, record)


def run(ctx):
    """Skip when off or unmerged; otherwise deploy now (on-merge), or ask first (button)."""
    cfg = _settings(ctx)
    name, mode = cfg.get("with", "none"), cfg.get("mode", "off")
    merged = ctx.things.get("merged")
    if merged in NOT_MERGED:
        _stop_preview(ctx)
    if name == "none" or mode == "off":
        return StepResult("skip", ["deploy is off for this project"])
    if merged in NOT_MERGED:
        return StepResult("skip", ["nothing merged, nothing to deploy"])
    if mode == "button" and (ctx.answer or {}).get("action") != "deploy":
        return _button_gate(ctx, merged, name)
    return _deploy(ctx, merged)
