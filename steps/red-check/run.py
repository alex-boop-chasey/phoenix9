"""Red check: the new checks must FAIL before anything is built; passing now means they prove nothing,
and crashing in their own setup (checklint.broken_reason) means they are broken, not red."""
from phoenix9 import atomic, checklint, checklock, docker, keys, scrub
from phoenix9.aistep import profile_test, project_domains
from phoenix9.stepctx import StepResult


def _runs(files: list[str], commands: list[str]) -> list[tuple[str, list[str]]]:
    """(command, the check files it runs): one per file for shell checks, else one for all."""
    if len(commands) == len(files) and len(files) > 1:
        return [(c, [f]) for c, f in zip(commands, files)]
    return [(c, files) for c in commands]


def run(ctx):
    """Run the locked checks in check containers; every run must exit non-zero without crashing in the checks."""
    files = [str(f) for f in ctx.things.get("checks") or []]
    runs = _runs(files, checklock.check_commands(profile_test(ctx), files))
    n = ctx.task["number"]
    folder = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "red-check.txt"
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()), project_domains(ctx))
    passed, broken, texts = [], [], []
    for i, (command, checks) in enumerate(runs, 1):
        part = out if len(runs) == 1 else folder / f"red-check-{i}.txt"
        with keys.env_file(ctx.project.name) as env_file:
            rc, _ = docker.run_check_container(
                ctx.adapters.docker, ctx.project.name, ctx.run.id, n, ctx.attempt, profile.get("image", ""),
                ctx.worktree, command, env_file, domains, 30, stdout_path=part,
                role="red-check" if len(runs) == 1 else f"red-check-{i}",
                mounts=[docker.Mount(folder, "/out", ro=False)])
        text = scrub.scrub(part.read_text(errors="replace")) if part.exists() else ""
        if len(runs) == 1:
            if part.exists():
                atomic.write_text(out, text)
        else:
            part.unlink(missing_ok=True)
            texts.append(f"$ {command}\nexit {rc}\n{text}")
        ctx.log(f"{command} -> exit {rc}")
        if rc == 0:
            passed += checks
            continue
        why = checklint.broken_reason(text, checks)
        if why:
            broken.append(why)
    if texts:
        atomic.write_text(out, "\n".join(texts))
    reasons = []
    if passed:
        reasons.append("The checks already pass before anything was built, so they prove nothing: " + ", ".join(passed))
    if broken:
        reasons.append(f"The checks are broken, not red: they crashed in their own setup ({'; '.join(broken)}), "
                       "so they would fail whatever the code does. The Check-writer writes them again; a check "
                       "must set up everything it uses itself.")
    return StepResult("fail", reasons) if reasons else StepResult("pass")
