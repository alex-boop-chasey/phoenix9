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
