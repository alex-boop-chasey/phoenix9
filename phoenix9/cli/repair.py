"""Commands for `phoenix repair`: check a run, undo a repair of a run."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import repair


def add(sub, common) -> None:
    """Register the repair group."""
    group = sub.add_parser("repair", help="look into a run that went wrong and put it right").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("check", parents=[common], help="look for problems in a run")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.set_defaults(func=check)
    p = group.add_parser("undo", parents=[common], help="undo a repair (default: the newest snapshot)")
    p.add_argument("run_id")
    p.add_argument("--project", help="the project of the run (the run id alone is enough)")
    p.add_argument("--to", type=int, help="the snapshot number to go back to")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=undo)


def undo(args) -> int:
    """Undo a repair of a run."""
    if not args.yes:
        return problem(args, "Undo puts the run's files and worktree back as an earlier snapshot had them. "
                             "Add --yes to confirm.")
    r = repair.undo(args.run_id, to=args.to, who=args.who, project=args.project)
    return show(args, {"ok": True, **r}, f"Undone: {args.run_id} is back as snapshot {r['restored']} had it "
                                         f"(a new snapshot {r['snapshot']} keeps what it was).")


def check(args) -> int:
    """Check a run: "No problems found" (exit 0) or a numbered list of what is wrong (exit 1)."""
    r = repair.check(args.run_id, project=args.project)
    text = "No problems found" if r["ok"] else "\n".join(f"{i}. {p['text']}" for i, p in enumerate(r["problems"], 1))
    show(args, {"ok": r["ok"], **r}, text)
    return 0 if r["ok"] else 1
