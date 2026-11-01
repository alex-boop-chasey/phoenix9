"""Verify: runs the task's checks (and in full scope the whole suite) in a fresh container and writes the test report."""
import importlib
import shutil

from phoenix9 import atomic, checklock, docker, git, reports, scrub, settings
from phoenix9.aistep import profile_test
from phoenix9.stepctx import StepResult

DEFAULT_ARGS = {"pytest-junit": "--junitxml=/out/pytest.xml",
                "vitest-json": "--reporter=json --outputFile=/out/vitest.json"}


def _keys(ctx, name):
    """Call phoenix9.keys.<name>(project) if that module and function exist (project keys arrive in a later step)."""
    try:
        fn = getattr(importlib.import_module("phoenix9.keys"), name, None)
    except ImportError:
        return None
    return fn(ctx.project) if fn else None


def _readers(test) -> list:
    """The profile's report reader names, checked against the known readers."""
    names = test.get("report", "exit-code")
    names = [names] if isinstance(names, str) else list(names)
    reports.check_names(names)
    return names


def _report_args(test, readers) -> str:
    """The profile's report_args, or the usual ones for the readers when it has none."""
    return test.get("report_args") or " ".join(DEFAULT_ARGS[r] for r in readers if r in DEFAULT_ARGS)


def _jobs(ctx, test, readers, scope) -> list:
    """The things to run: (label, command, reader names, expected check files)."""
    args = _report_args(test, readers)
    jobs = []
    if scope == "full" and test.get("cmd"):
        jobs.append(("suite", f"{test['cmd']} {args}".strip(), readers, []))
    files = ctx.things.get("checks")
    if isinstance(files, (list, tuple)) and files:
        template = test.get("check_command") or test.get("cmd") or ""
        command = template.replace("{files}", " ".join(str(f) for f in files))
        jobs.append(("checks", f"{command} {args}".strip(), readers, [str(f) for f in files]))
    else:
        done = (ctx.task or {}).get("done_when", [])
        jobs += [(f"check-{i}", c["command"], ["exit-code"], []) for i, c in enumerate(done, 1) if c.get("command")]
    return jobs


def _stash(out_dir, label) -> None:
    """Move the report files of one command into out_dir/<label>/ so the next command cannot overwrite them."""
    dest = out_dir / label
    dest.mkdir(exist_ok=True)
    for name in reports.REPORT_FILES.values():
        if (out_dir / name).exists():
            shutil.move(str(out_dir / name), str(dest / name))


def run(ctx):
    """Run the checks in a fresh check container on a clean checkout, judge the reports, write test-report.json."""
    n = ctx.task["number"] if ctx.task else 0
    problems = checklock.verify(ctx.run.folder, n, ctx.worktree)
    if problems:
        return StepResult("fail", problems)
    test = profile_test(ctx)
    try:
        jobs = _jobs(ctx, test, _readers(test), ctx.step.settings.get("scope", "task"))
    except settings.SettingsError as err:
        return StepResult("fail", [str(err)])
    if not jobs:
        return StepResult("fail", [f"Task {n} has nothing Phoenix can run to verify it"])
    folder = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}"
    out_dir = folder / "verify"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    docker.hand_to_agent(ctx.adapters.docker, out_dir)
    checkout = folder / "verify-checkout"
    git.rmtree(checkout)
    git.fresh_checkout(ctx.worktree, checkout)
    try:
        parts, logs = _run_jobs(ctx, jobs, checkout, out_dir, n)
        broken = checklock.verify(ctx.run.folder, n, checkout)
    finally:
        git.remove_checkout(ctx.worktree, checkout)
    report = reports.combine(parts)
    if broken:
        report.ok = False
        report.notes.insert(0, "during verify: " + "; ".join(broken))
    atomic.write_json(out_dir / "test-report.json", report.to_dict())
    if report.ok:
        return StepResult("pass", produces={"test-report": str(out_dir / "test-report.json")})
    bad = next((log for part, log in zip(parts, logs) if not part.ok), logs[-1])
    return StepResult("fail", [reports.feedback(report, bad)],
                      produces={"test-report": str(out_dir / "test-report.json")})


def _run_jobs(ctx, jobs, checkout, out_dir, n, log_dir=None):
    """Run each job in its own check container; return (the reports, the log files). Logs go to log_dir/<i>.txt when given."""
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()))
    env_file = _keys(ctx, "container_env")
    secrets = list(_keys(ctx, "secret_values") or [])
    parts, logs = [], []
    for i, (label, command, readers, expected) in enumerate(jobs, 1):
        log = log_dir / f"{i}.txt" if log_dir else ctx.run.folder / "logs" / f"verify-{n}-{i}.txt"
        rc, _ = docker.run_check_container(
            ctx.adapters.docker, ctx.project.name, ctx.run.id, n, ctx.attempt, profile.get("image", ""),
            checkout, command, env_file, domains, 30, stdout_path=log, role=f"verify-{i}",
            mounts=[docker.Mount(out_dir, "/out", ro=False)])
        if "exit-code" in readers:
            atomic.write_text(out_dir / reports.REPORT_FILES["exit-code"], f"{rc}\n")   # Phoenix writes this itself
        reports.redact_reports(out_dir, secrets)
        scrubbed = scrub.scrub(log.read_text(errors="replace")) if log.exists() else ""
        atomic.write_text(log, scrubbed)
        ctx.log(f"{command} -> exit {rc}")
        parts.append(reports.judge(rc, out_dir, readers, expected, rc == docker.TIMEOUT_RC))
        _stash(out_dir, label)
        logs.append(log)
    return parts, logs
