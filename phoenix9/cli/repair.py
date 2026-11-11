"""Commands for `phoenix repair`: check a run, write its report, apply a repair note, undo a repair, resume a run."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import common, repair


def add(sub, common) -> None:
    """Register the repair group."""
    group = sub.add_parser("repair", help="look into a run that went wrong and put it right").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("check", parents=[common], help="look for problems in a run")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.set_defaults(func=check)
    p = group.add_parser("diagnose", parents=[common], help="say why a run stopped or failed and what could fix it")
    p.add_argument("run_id")
    p.add_argument("--project", required=True, help="the project of the run")
    p.set_defaults(func=diagnose)
    p = group.add_parser("report", parents=[common], help="write and show the plain-English report of a run")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.set_defaults(func=report)
    p = group.add_parser("apply", parents=[common], help="apply a repair note (snapshot, steps, check, roll back if bad)")
    p.add_argument("note", help="the repair note (a markdown file)")
    p.add_argument("--dry-run", action="store_true", help="only show what it would do; change nothing")
    p.add_argument("--approve-unlock", action="store_true", help="allow steps that unlock locked checks")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=apply)
    p = group.add_parser("undo", parents=[common], help="undo a repair (default: the newest snapshot)")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.add_argument("--to", type=int, help="the snapshot number to go back to")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=undo)
    p = group.add_parser("resume", parents=[common], help="let the runner carry on with a repaired run")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=resume)
    _add_new(group, common)


def _run_parser(group, common, name: str, help_text: str, func, yes: bool):
    """Add one repair command that takes a run id (and --project, and --yes when it discards work)."""
    p = group.add_parser(name, parents=[common], help=help_text)
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    if yes:
        p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=func)
    return p


def _add_new(group, common) -> None:
    """Register rerun, resume-from, skip, rewrite-checks, max-tries and restart."""
    p = _run_parser(group, common, "rerun", "run a task or a finish step again", rerun, True)
    p.add_argument("--task", type=int, help="the task number to run again")
    p.add_argument("--finish-step", help="the finish step to run again")
    p = _run_parser(group, common, "resume-from", "carry on with a run from a task", resume_from, True)
    p.add_argument("--task", type=int, required=True, help="the task number to carry on from")
    p = _run_parser(group, common, "skip", "skip a task, with a reason", skip, True)
    p.add_argument("--task", type=int, required=True, help="the task number to skip")
    p.add_argument("--why", required=True, help="the reason, in one line")
    p = _run_parser(group, common, "rewrite-checks", "rewrite the checks of a task, with a reason", rewrite_checks, True)
    p.add_argument("--task", type=int, required=True, help="the task number whose checks are rewritten")
    p.add_argument("--why", required=True, help="the reason, in one line")
    p = _run_parser(group, common, "max-tries", "allow more tries per task in this run", max_tries, False)
    p.add_argument("--tries", type=int, required=True, help="the new number of tries per task")
    p = _run_parser(group, common, "restart", "start the build again on another preset", restart, False)
    p.add_argument("--preset", required=True, help="the preset to restart on")
    p.set_defaults(project_required=True)


def undo(args) -> int:
    """Undo a repair of a run."""
    if not args.yes:
        return problem(args, "Undo puts the run's files and worktree back as an earlier snapshot had them. "
                             "Add --yes to confirm.")
    r = repair.undo(args.run_id, to=args.to, who=args.who, project=args.project)
    return show(args, {"ok": True, **r}, f"Undone: {args.run_id} is back as snapshot {r['restored']} had it "
                                         f"(a new snapshot {r['snapshot']} keeps what it was).")


def resume(args) -> int:
    """Resume a repaired run so the runner carries on with it."""
    if not args.yes:
        return problem(args, "Resume lets the runner carry on with this run. Add --yes to confirm.")
    r = repair.resume(args.run_id, who=args.who, project=args.project)
    return show(args, {"ok": True, **r}, f"Resumed: {args.run_id} is {r['status']}; the runner carries on.")


def check(args) -> int:
    """Check a run: "No problems found" (exit 0) or a numbered list of what is wrong (exit 1)."""
    r = repair.check(args.run_id, project=args.project)
    common.record_command(args.who, f"repair check {args.run_id}", r["project"])
    text = "No problems found" if r["ok"] else "\n".join(f"{i}. {p['text']}" for i, p in enumerate(r["problems"], 1))
    show(args, {"ok": r["ok"], **r}, text)
    return 0 if r["ok"] else 1


def diagnose(args) -> int:
    """Show why a run stopped or failed, what was tried and the repairs that fit."""
    r = repair.diagnose(args.project, args.run_id)
    common.record_command(args.who, f"repair diagnose {args.run_id}", args.project)
    lines = [r["cause"], *r["tried"]] + [f"Option: {o['label']} ({o['control']})" for o in r["options"]]
    return show(args, r, "\n".join(lines))


def report(args) -> int:
    """Write the run report and show it."""
    r = repair.report(args.run_id, project=args.project)
    common.record_command(args.who, f"repair report {args.run_id}", r["project"])
    return show(args, {"ok": True, **r}, r["text"])


def apply(args) -> int:
    """Apply a repair note (or show a dry run); exit 1 when it was refused or rolled back."""
    if not args.dry_run and not args.yes:
        return problem(args, "Applying a note changes the run's state and worktree. "
                             "Add --dry-run to look first, or --yes to confirm.")
    r = repair.apply(args.note, who=args.who, dry_run=args.dry_run, approve_unlock=args.approve_unlock)
    head = "Dry run (nothing was changed)" if r["dry_run"] else (
        "Rolled back: the repair did not pass its check" if r["rolled_back"] else "Applied")
    lines = [head + ":"] + [f"{i}. {s}" for i, s in enumerate(r["steps"], 1)]
    if r.get("refused"):
        lines.append("Refused: " + r["refused"])
    after = r["check_after"]
    lines.append("Check after: " + ("not run" if after is None else "; ".join(after) or "no problems"))
    show(args, r, "\n".join(lines))
    return 0 if r["ok"] else 1


def _confirm(args, what: str):
    """Return a refusal (exit code) when --yes is missing, else None."""
    if args.yes:
        return None
    return problem(args, f"{what} Add --yes to confirm.")


def _outcome(args, r: dict, done: str) -> int:
    """Show the result of a repair note: done in plain words, or the rollback; exit 1 when rolled back."""
    if r.get("rolled_back"):
        show(args, {"ok": False, **r}, "Rolled back: the repair did not pass its check.")
        return 1
    return show(args, {"ok": True, **r}, done)


def rerun(args) -> int:
    """Run a task or a finish step of a run again."""
    refused = _confirm(args, "Running again throws away the work of that step.")
    if refused is not None:
        return refused
    r = repair.rerun_step(args.run_id, task=args.task, finish_step=args.finish_step, who=args.who)
    what = f"task {args.task}" if args.task is not None else f"finish step {args.finish_step}"
    return _outcome(args, r, f"Done: {what} of {args.run_id} will run again.")


def resume_from(args) -> int:
    """Carry on with a run from a task."""
    refused = _confirm(args, f"Carrying on from task {args.task} runs it again and throws away its work.")
    if refused is not None:
        return refused
    r = repair.resume_from(args.run_id, args.task, who=args.who)
    return _outcome(args, r, f"Done: {args.run_id} carries on from task {args.task}.")


def skip(args) -> int:
    """Skip a task of a run, with a reason."""
    refused = _confirm(args, f"Skipping task {args.task} means it is not built.")
    if refused is not None:
        return refused
    r = repair.skip_task(args.run_id, args.task, args.why, who=args.who)
    return _outcome(args, r, f"Done: task {args.task} of {args.run_id} is skipped.")


def rewrite_checks(args) -> int:
    """Rewrite the checks of a task, with a reason."""
    refused = _confirm(args, f"Rewriting the checks of task {args.task} replaces them.")
    if refused is not None:
        return refused
    r = repair.rewrite_checks(args.run_id, args.task, args.why, who=args.who)
    return _outcome(args, r, f"Done: the checks of task {args.task} of {args.run_id} will be rewritten.")


def max_tries(args) -> int:
    """Allow more tries per task in a run."""
    r = repair.raise_max_tries(args.run_id, args.tries, who=args.who)
    return _outcome(args, r, f"Done: {args.run_id} now allows {args.tries} tries per task.")


def restart(args) -> int:
    """Start the build of a stopped or failed run again on another preset."""
    if not args.project:
        return problem(args, "Say which project the run belongs to with --project.")
    r = repair.restart_on_preset(args.project, args.run_id, args.preset, who=args.who)
    return show(args, {"ok": True, **r}, f"Restarted: {args.run_id} is started again as {r['new_run_id']} "
                                         f"on the {r['preset']} preset.")
