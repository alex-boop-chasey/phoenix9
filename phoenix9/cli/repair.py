"""Commands for `phoenix repair`: undo a repair of a run."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import repair


def add(sub, common) -> None:
    """Register the repair group."""
    group = sub.add_parser("repair", help="look into a run that went wrong and put it right").add_subparsers(
        dest="action", metavar="ACTION", required=True)
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
