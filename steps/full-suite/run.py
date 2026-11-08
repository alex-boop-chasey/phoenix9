"""Full suite: runs the project's whole test command on a clean checkout of the run branch and judges its report."""
import importlib.util
import shutil
from pathlib import Path

from phoenix9 import atomic, docker, git, reports, settings
from phoenix9.aistep import profile_test
from phoenix9.stepctx import StepResult

NO_SUITE = "the profile has no full suite command"
HEAD_FILE = "full-suite-head.txt"      # the worktree head the last passing full suite ran on (repair reruns check it)


def _verify():
    """Load the Verify step's module, to reuse its helpers."""
    path = Path(__file__).resolve().parent.parent / "verify" / "run.py"
    spec = importlib.util.spec_from_file_location("verify_run_for_full_suite", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(ctx):
    """Run the profile's suite command in a fresh check container, write final-report.json, pass or fail on the report."""
    test = profile_test(ctx)
    if not test.get("cmd"):
        return StepResult("skip", [NO_SUITE])
    verify = _verify()
    try:
        readers = verify._readers(test)
    except settings.SettingsError as err:
        return StepResult("fail", [str(err)])
    command = f"{test['cmd']} {verify._report_args(test, readers)}".strip()
    out_dir = ctx.run.folder / "full-suite"
    log_dir = ctx.run.folder / "logs" / "full-suite"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    docker.hand_to_agent(ctx.adapters.docker, out_dir)
    checkout = ctx.run.folder / "full-suite-checkout"
    git.rmtree(checkout)
    git.fresh_checkout(ctx.worktree, checkout)
    try:
        parts, logs = verify._run_jobs(ctx, [("suite", command, readers, [])], checkout, out_dir, 0, log_dir)
    finally:
        git.remove_checkout(ctx.worktree, checkout)
    report = reports.combine(parts)
    atomic.write_json(ctx.run.folder / "final-report.json", report.to_dict())
    if report.ok:
        atomic.write_text(ctx.run.folder / HEAD_FILE, ctx.adapters.git.head(ctx.worktree) + "\n")  # what it passed on
        return StepResult("pass", produces={"test-report": str(ctx.run.folder / "final-report.json")})
    return StepResult("fail", [reports.feedback(report, logs[-1])])
