"""Branch: makes the run's worktree and records how main's tests do before any work."""
from phoenix9 import atomic, docker, keys, paths
from phoenix9.aistep import project_domains
from phoenix9.stepctx import StepResult


def run(ctx):
    """Make the worktree, run the profile's test command on it, and produce `baseline`."""
    work = paths.work(ctx.project.name, ctx.run.id)
    if not work.is_dir():
        ctx.adapters.git.make_worktree(ctx.project.code_dir, ctx.run.id, work)
    test = ctx.project.profile.get("test") or {}
    command = test.get("cmd", "")
    if not command:
        baseline = {"ran": False, "exit_code": None, "passed": None}
    else:
        domains = docker.write_domains_file(ctx.project.name, ctx.project.profile.get("allowed_domains", ()),
                                           project_domains(ctx))
        with keys.env_file(ctx.project.name) as env_file:
            rc, out = docker.run_check_container(
                ctx.adapters.docker, ctx.project.name, ctx.run.id, 0, 1, ctx.project.profile.get("image", ""),
                work, command, env_file, domains, 30, stdout_path=ctx.run.folder / "logs" / "baseline.txt",
                role="baseline")
        baseline = {"ran": True, "command": command, "exit_code": rc, "passed": rc == 0,
                    "output": str(out.relative_to(ctx.run.folder))}
    atomic.write_json(ctx.run.folder / "baseline.json", baseline)
    return StepResult("pass", produces={"baseline": baseline})
