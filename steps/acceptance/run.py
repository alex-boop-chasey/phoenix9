"""Acceptance: runs each backticked check of the task in the worktree; exit codes are the gate."""
from phoenix9 import docker
from phoenix9.stepctx import StepResult


def run(ctx):
    """Run every check command in a check container and record the exit codes."""
    commands = [c["command"] for c in (ctx.task or {}).get("done_when", []) if c.get("command")]
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()))
    number = ctx.task["number"] if ctx.task else 0
    codes, failed = [], []
    for i, command in enumerate(commands, 1):
        out_path = ctx.run.folder / "logs" / f"acceptance-{number}-{i}.txt"
        rc, _ = docker.run_check_container(
            ctx.adapters.docker, ctx.project.name, ctx.run.id, number, ctx.attempt, profile.get("image", ""),
            ctx.worktree, command, None, domains, 30, stdout_path=out_path, role="acceptance")
        codes.append({"command": command, "exit_code": rc})
        ctx.log(f"{command} -> exit {rc}")
        if rc != 0:
            failed.append(f"`{command}` exited with {rc}")
    produced = {"exit-codes": codes}
    return StepResult("fail", failed, produces=produced) if failed else StepResult("pass", produces=produced)
