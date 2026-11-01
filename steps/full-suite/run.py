"""Full suite: runs the project's whole test command once all tasks are done."""
from phoenix9 import docker
from phoenix9.stepctx import StepResult


def run(ctx):
    """Run the profile's test command in the worktree; the exit code decides."""
    command = (ctx.project.profile.get("test") or {}).get("cmd", "")
    if not command:
        return StepResult("skip", ["The profile has no test command."])
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()))
    rc, _ = docker.run_check_container(
        ctx.adapters.docker, ctx.project.name, ctx.run.id, 0, 1, profile.get("image", ""), ctx.worktree,
        command, None, domains, 30, stdout_path=ctx.run.folder / "logs" / "full-suite.txt", role="full-suite")
    return StepResult("pass") if rc == 0 else StepResult("fail", [f"`{command}` exited with {rc}"])
