"""Running a task's checks in check containers on a clean checkout, shared by Acceptance and Verify."""
import shutil
from pathlib import Path

from phoenix9 import atomic, checklock, docker, keys, reports, scrub
from phoenix9.aistep import project_domains

DEFAULT_ARGS = {"pytest-junit": "--junitxml=/out/pytest.xml",
                "vitest-json": "--reporter=json --outputFile=/out/vitest.json"}
RESULTS_FILE = "acceptance-results.json"
CHECK_LABELS = ("checks", "check-")


def readers(test) -> list:
    """The profile's report reader names, checked against the known readers."""
    names = test.get("report", "exit-code")
    names = [names] if isinstance(names, str) else list(names)
    reports.check_names(names)
    return names


def report_args(test, names) -> str:
    """The profile's report_args, or the usual ones for the readers when it has none."""
    return test.get("report_args") or " ".join(DEFAULT_ARGS[r] for r in names if r in DEFAULT_ARGS)


def check_jobs(ctx, test, names) -> list:
    """The jobs that run the task's own checks: (label, command, reader names, expected check files)."""
    args = report_args(test, names)
    files = ctx.things.get("checks")
    if isinstance(files, (list, tuple)) and files:
        checks = [str(f) for f in files]
        commands = checklock.check_commands(test, checks)
        if len(commands) == 1:
            return [("checks", f"{commands[0]} {args}".strip(), names, checks)]
        return [(f"checks-{i}", f"{c} {args}".strip(), names, [f])      # one shell check per run
                for i, (c, f) in enumerate(zip(commands, checks), 1)]
    done = (ctx.task or {}).get("done_when", [])
    return [(f"check-{i}", c["command"], ["exit-code"], []) for i, c in enumerate(done, 1) if c.get("command")]


def is_check_job(job) -> bool:
    """True for a job made by check_jobs (not the suite or affected tests)."""
    return job[0].startswith(CHECK_LABELS)


def stash(out_dir, label) -> None:
    """Move the report files of one command into out_dir/<label>/ so the next command cannot overwrite them."""
    dest = out_dir / label
    dest.mkdir(exist_ok=True)
    for name in reports.REPORT_FILES.values():
        if (out_dir / name).exists():
            shutil.move(str(out_dir / name), str(dest / name))


def run_jobs(ctx, jobs, checkout, out_dir, n, log_dir=None, prefix="verify"):
    """Run each job in its own check container; return (the reports, the log files, the exit codes)."""
    profile = ctx.project.profile
    domains = docker.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()), project_domains(ctx))
    secrets = keys.secret_values(ctx.project.name)
    parts, logs, codes = [], [], []
    for i, (label, command, names, expected) in enumerate(jobs, 1):
        log = log_dir / f"{i}.txt" if log_dir else ctx.run.folder / "logs" / f"{prefix}-{n}-{i}.txt"
        with keys.env_file(ctx.project.name) as env_file:
            rc, _ = docker.run_check_container(
                ctx.adapters.docker, ctx.project.name, ctx.run.id, n, ctx.attempt, profile.get("image", ""),
                checkout, command, env_file, domains, 30, stdout_path=log, role=f"{prefix}-{i}",
                mounts=[docker.Mount(out_dir, "/out", ro=False)])
        if "exit-code" in names:
            atomic.write_text(out_dir / reports.REPORT_FILES["exit-code"], f"{rc}\n")   # Phoenix writes this itself
        reports.redact_reports(out_dir, secrets)
        scrubbed = scrub.scrub(log.read_text(errors="replace")) if log.exists() else ""
        atomic.write_text(log, scrubbed)
        ctx.log(f"{command} -> exit {rc}")
        parts.append(reports.judge(rc, out_dir, names, expected, rc == docker.TIMEOUT_RC, command))
        stash(out_dir, label)
        logs.append(log)
        codes.append(rc)
    return parts, logs, codes


def verify_is_on(run_folder) -> bool:
    """True when the run's plan has the verify step in each task."""
    plan = atomic.read_json(run_folder / "plan.json") or {}
    return "verify" in (plan.get("groups") or {}).get("task", ())


def save_results(folder, ctx, tree, jobs, parts, logs, codes) -> None:
    """Record what Acceptance ran on the clean checkout, tied to this attempt and the tree it tested."""
    items = [{"label": j[0], "command": j[1], "readers": list(j[2]), "expected": list(j[3]), "exit_code": rc,
              "report": p.to_dict(), "log": str(log)} for j, p, log, rc in zip(jobs, parts, logs, codes)]
    atomic.write_json(folder / RESULTS_FILE, {"run": ctx.run.id, "task": (ctx.task or {}).get("number", 0),
                                               "attempt": ctx.attempt, "tree": tree, "jobs": items})


def load_results(folder, ctx, tree, jobs):
    """Acceptance's recorded results when they are for this run, task, attempt, tree and these jobs, else None."""
    data = atomic.read_json(folder / RESULTS_FILE)
    if not isinstance(data, dict):
        return None
    same = (data.get("run") == ctx.run.id and data.get("task") == (ctx.task or {}).get("number", 0)
            and data.get("attempt") == ctx.attempt and data.get("tree") and data.get("tree") == tree)
    items = data.get("jobs")
    if not same or not isinstance(items, list) or len(items) != len(jobs):
        return None
    if any(it.get("label") != j[0] or it.get("command") != j[1] for it, j in zip(items, jobs)):
        return None
    try:
        return [(reports.Report(**it["report"]), Path(it["log"])) for it in items]
    except (TypeError, KeyError):
        return None
