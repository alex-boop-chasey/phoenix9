"""Red check: the new checks must FAIL before anything is built; passing now means they prove nothing,
and crashing in their own setup (checklint.broken_reason) means they are broken, not red."""
from phoenix9 import atomic, checklint, docker, keys, scrub
from phoenix9.aistep import profile_test, project_domains
from phoenix9.stepctx import StepResult


def run(ctx):
    """Run the locked checks in a check container; require a non-zero exit that is not a crash in the checks."""
    files = [str(f) for f in ctx.things.get("checks") or []]
    test = profile_test(ctx)
    command = (test.get("check_command") or test.get("cmd") or "").replace("{files}", " ".join(files))
    n = ctx.task["number"]
    folder = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "red-check.txt"
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()), project_domains(ctx))
    with keys.env_file(ctx.project.name) as env_file:
        rc, _ = docker.run_check_container(
            ctx.adapters.docker, ctx.project.name, ctx.run.id, n, ctx.attempt, profile.get("image", ""),
            ctx.worktree, command, env_file, domains, 30, stdout_path=out, role="red-check",
            mounts=[docker.Mount(folder, "/out", ro=False)])
    text = ""
    if out.exists():
        text = scrub.scrub(out.read_text(errors="replace"))
        atomic.write_text(out, text)
    ctx.log(f"{command} -> exit {rc}")
    if rc == 0:
        return StepResult("fail", ["The checks already pass before anything was built, "
                                   "so they prove nothing: " + ", ".join(files)])
    broken = checklint.broken_reason(text, files)
    if broken:
        return StepResult("fail", [f"The checks are broken, not red: they crashed in their own setup "
                                   f"({broken}), so they would fail whatever the code does. The Check-writer "
                                   "writes them again; a check must set up everything it uses itself."])
    return StepResult("pass")
