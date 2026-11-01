"""Acceptance: runs the task's checks in check containers; exit codes are the gate."""
import time

from phoenix9 import atomic, checklock, docker, keys, scrub
from phoenix9.aistep import profile_test, project_domains
from phoenix9.stepctx import StepResult

TAIL_LINES = 60


def _commands(ctx, test):
    """Return (commands to run, bullets shown but not run)."""
    files = ctx.things.get("checks")
    if isinstance(files, (list, tuple)) and files:
        template = test.get("check_command") or test.get("cmd") or ""
        return [template.replace("{files}", " ".join(str(f) for f in files))], []
    done = (ctx.task or {}).get("done_when", [])
    return [c["command"] for c in done if c.get("command")], [c.get("text", "") for c in done if not c.get("command")]


def _tail(path):
    """The last 60 lines of an output file, scrubbed."""
    text = path.read_text(errors="replace") if path.exists() else ""
    return scrub.scrub("\n".join(text.splitlines()[-TAIL_LINES:]))


def _reason_line(tail):
    """The first failing test line, else the last non-empty line."""
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith(("FAILED", "FAIL ", "✗", "not ok")) or "Error" in ln:
            return ln[:200]
    return lines[-1][:200] if lines else "no output"


def run(ctx):
    """Run every check command in a fresh check container and record the exit codes."""
    n = ctx.task["number"] if ctx.task else 0
    problems = checklock.verify(ctx.run.folder, n, ctx.worktree)
    if problems:
        return StepResult("fail", problems)
    commands, shown = _commands(ctx, profile_test(ctx))
    if not commands:
        return StepResult("fail", [f"Task {n} has nothing Phoenix can run to check it"])
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()), project_domains(ctx))
    folder = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}"
    folder.mkdir(parents=True, exist_ok=True)
    codes, failed, report = [], [], []
    for i, command in enumerate(commands, 1):
        out_path = ctx.run.folder / "logs" / f"acceptance-{n}-{i}.txt"
        started = time.monotonic()
        with keys.env_file(ctx.project.name) as env_file:
            rc, _ = docker.run_check_container(
                ctx.adapters.docker, ctx.project.name, ctx.run.id, n, ctx.attempt, profile.get("image", ""),
                ctx.worktree, command, env_file, domains, 30, stdout_path=out_path, role=f"acceptance-{i}")
        seconds = round(time.monotonic() - started, 1)
        tail = _tail(out_path)
        codes.append({"command": command, "exit_code": rc, "duration": seconds, "output": tail})
        report.append(f"$ {command}\nexit {rc} in {seconds}s\n{tail}\n")
        ctx.log(f"{command} -> exit {rc}")
        if rc != 0:
            failed.append(f"Check `{command}` failed (exit {rc}): {_reason_line(tail)}")
    report += [f"shown, not run: {text}" for text in shown]
    atomic.write_text(folder / "checks.txt", scrub.scrub("\n".join(report)) + "\n")
    produced = {"exit-codes": codes}
    return StepResult("fail", failed, produces=produced) if failed else StepResult("pass", produces=produced)
