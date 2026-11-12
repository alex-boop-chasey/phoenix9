"""Verify: runs the task's checks (and in full scope the whole suite) in a fresh container and writes the test report."""
import shutil

from phoenix9 import affected, atomic, checklock, docker, git, keys, reports, scrub, settings, state
from phoenix9.aistep import profile_test, project_domains
from phoenix9.stepctx import StepResult

DEFAULT_ARGS = {"pytest-junit": "--junitxml=/out/pytest.xml",
                "vitest-json": "--reporter=json --outputFile=/out/vitest.json"}


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
        names = [str(f) for f in files]
        commands = checklock.check_commands(test, names)
        if len(commands) == 1:
            jobs.append(("checks", f"{commands[0]} {args}".strip(), readers, names))
        else:                                       # one shell check per run (`sh a.sh b.sh` runs a.sh only)
            jobs += [(f"checks-{i}", f"{c} {args}".strip(), readers, [f])
                     for i, (c, f) in enumerate(zip(commands, names), 1)]
    else:
        done = (ctx.task or {}).get("done_when", [])
        jobs += [(f"check-{i}", c["command"], ["exit-code"], []) for i, c in enumerate(done, 1) if c.get("command")]
    return jobs


def _suite_job(test, readers) -> tuple:
    """The job that runs the whole suite."""
    return ("suite", f"{test['cmd']} {_report_args(test, readers)}".strip(), readers, [])


def _pending(ctx) -> list:
    """The tasks that passed since the run's last whole-suite pass, as [{number, title}] (kept in state.json)."""
    return list(state.load(ctx.run.folder).get("suite_pending") or [])


def _checkpoint_due(ctx, test, n) -> bool:
    """True when this task is the suite_every-th to pass since the last whole-suite pass."""
    every = int(ctx.step.settings.get("suite_every", 5) or 0)
    others = [t for t in _pending(ctx) if t.get("number") != n]
    return every > 0 and bool(test.get("cmd")) and len(others) + 1 >= every


def _changed_files(ctx, checkout, n) -> list:
    """Every path changed since the task's attempt began, measured on the clean checkout."""
    task = state.load(ctx.run.folder)["tasks"].get(str(n)) or {}
    changes = git.diff_changes(checkout, task.get("attempt_base") or "HEAD")
    return [p for c in changes for p in (c.path, c.old_path) if p]


def _tracked(checkout) -> list:
    """Every tracked file in the checkout."""
    return [p for p in git.git(checkout, "ls-files", "-z").split("\0") if p]


def _affected_plan(ctx, test, readers, checkout, n) -> dict:
    """What to add to the task's checks in the affected scope: {mode, picked, jobs, checkpoint}."""
    if _checkpoint_due(ctx, test, n):
        return {"mode": "suite", "picked": [], "jobs": [_suite_job(test, readers)], "checkpoint": True}
    pick = affected.pick(test, _changed_files(ctx, checkout, n), _tracked(checkout), checkout)
    if pick["mode"] == "all" and test.get("cmd"):
        return {"mode": "suite", "picked": [], "jobs": [_suite_job(test, readers)], "checkpoint": False}
    if pick["mode"] == "some":
        command = f"{pick['command']} {_report_args(test, readers)}".strip()
        return {"mode": "affected", "picked": list(pick["files"]),
                "jobs": [("affected", command, readers, [])], "checkpoint": False}
    return {"mode": "checks", "picked": [], "jobs": [], "checkpoint": False}


def _record_pass(ctx, n, title, suite_ran) -> None:
    """After a passed task: a whole-suite pass clears the list, otherwise the task joins it (atomic)."""
    def change(s):
        pending = [t for t in s.get("suite_pending") or [] if t.get("number") != n]
        s["suite_pending"] = [] if suite_ran else pending + [{"number": n, "title": title}]
    state.update(ctx.run.folder, change)


def _checkpoint_reason(ctx, n) -> str:
    """The plain-English reason a failing checkpoint gives: the break may come from any task since the last pass."""
    tasks = [t for t in _pending(ctx) if t.get("number") != n]
    tasks.append({"number": n, "title": (ctx.task or {}).get("title", "")})
    names = "; ".join(f"task {t['number']} ({t['title']})" for t in tasks)
    return ("The whole test suite failed at a checkpoint. The break may come from any task since the last "
            f"whole-suite pass: {names}.")


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
    scope = ctx.step.settings.get("scope", "task")
    try:
        readers = _readers(test)
        jobs = _jobs(ctx, test, readers, scope)
    except settings.SettingsError as err:
        return StepResult("fail", [str(err)])
    if not jobs and scope != "affected":
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
        plan = {"mode": "suite" if scope == "full" and test.get("cmd") else "checks", "picked": [],
                "jobs": [], "checkpoint": False}
        if scope == "affected":
            plan = _affected_plan(ctx, test, readers, checkout, n)
            jobs = plan["jobs"] + jobs
        if not jobs:
            return StepResult("fail", [f"Task {n} has nothing Phoenix can run to verify it"])
        parts, logs = _run_jobs(ctx, jobs, checkout, out_dir, n)
        broken = checklock.verify(ctx.run.folder, n, checkout)
    finally:
        git.remove_checkout(ctx.worktree, checkout)
    report = reports.combine(parts)
    if broken:
        report.ok = False
        report.notes.insert(0, "during verify: " + "; ".join(broken))
    atomic.write_json(out_dir / "test-report.json", {**report.to_dict(), "mode": plan["mode"], "picked": plan["picked"]})
    if scope == "affected" and report.ok:
        _record_pass(ctx, n, (ctx.task or {}).get("title", ""), plan["mode"] == "suite")
    if report.ok:
        return StepResult("pass", produces={"test-report": str(out_dir / "test-report.json")})
    bad = next((log for part, log in zip(parts, logs) if not part.ok), logs[-1])
    suite_failed = plan["checkpoint"] and any(p.ok is False for p, j in zip(parts, jobs) if j[0] == "suite")
    reasons = [reports.feedback(report, bad)]
    return StepResult("fail", ([_checkpoint_reason(ctx, n)] if suite_failed else []) + reasons,
                      produces={"test-report": str(out_dir / "test-report.json")})


def _run_jobs(ctx, jobs, checkout, out_dir, n, log_dir=None):
    """Run each job in its own check container; return (the reports, the log files). Logs go to log_dir/<i>.txt when given."""
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()), project_domains(ctx))
    secrets = keys.secret_values(ctx.project.name)
    parts, logs = [], []
    for i, (label, command, readers, expected) in enumerate(jobs, 1):
        log = log_dir / f"{i}.txt" if log_dir else ctx.run.folder / "logs" / f"verify-{n}-{i}.txt"
        with keys.env_file(ctx.project.name) as env_file:
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
