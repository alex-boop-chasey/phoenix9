"""Branch: makes the run's worktree and records how main's tests do before any work."""
from phoenix9 import atomic, docker, git, keys, paths, suitepass
from phoenix9.aistep import project_domains
from phoenix9.stepctx import StepResult


def run(ctx):
    """Make the worktree, run the profile's test command on it, and produce `baseline`."""
    work = paths.work(ctx.project.name, ctx.run.id)
    if not work.is_dir():
        ctx.adapters.git.make_worktree(ctx.project.code_dir, ctx.run.id, work)
    test = ctx.project.profile.get("test") or {}
    command = test.get("cmd", "")
    hit = None
    if not command:
        baseline = {"ran": False, "exit_code": None, "passed": None}
    else:
        tree = git.tree_id(work)
        pass_key = suitepass.key_for(ctx, tree, command)
        hit = suitepass.lookup(ctx.project.name, pass_key)
    if hit:
        baseline = {"ran": False, "passed": True, "remembered": True, "exit_code": 0, "command": command,
                    "remembered_at": hit["at"],
                    "note": f"the whole suite already passed on exactly this code at {hit['at']}"}
        ctx.emit("suite.skipped", reason="remembered pass", step="branch", at=hit["at"])
    elif command:
        domains = docker.write_domains_file(ctx.project.name, ctx.project.profile.get("allowed_domains", ()),
                                           project_domains(ctx))
        with keys.env_file(ctx.project.name) as env_file:
            rc, out = docker.run_check_container(
                ctx.adapters.docker, ctx.project.name, ctx.run.id, 0, 1, ctx.project.profile.get("image", ""),
                work, command, env_file, domains, 30, stdout_path=ctx.run.folder / "logs" / "baseline.txt",
                role="baseline")
        baseline = {"ran": True, "command": command, "exit_code": rc, "passed": rc == 0,
                    "output": str(out.relative_to(ctx.run.folder))}
        if rc == 0:
            suitepass.remember(ctx.project.name, pass_key, {"step": "branch"})
    atomic.write_json(ctx.run.folder / "baseline.json", baseline)
    return StepResult("pass", produces={"baseline": baseline})
