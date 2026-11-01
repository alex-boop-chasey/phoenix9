"""Commands for `phoenix deploy now|status` and `phoenix deployers list`."""
from phoenix9.cli.output import show, table
from phoenix9.ops import deploy as ops


def add(sub, common) -> None:
    """Register the deploy and deployers groups."""
    group = sub.add_parser("deploy", help="deploy a project").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("now", parents=[common], help="deploy the project's main code now")
    p.add_argument("project")
    p.add_argument("--yes", action="store_true", help="go ahead")
    p.set_defaults(func=now)
    p = group.add_parser("status", parents=[common], help="last deploys, live address, last good commit")
    p.add_argument("project")
    p.set_defaults(func=status)
    group = sub.add_parser("deployers", help="the deployers library").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    group.add_parser("list", parents=[common], help="list deployers").set_defaults(func=deployers)


def now(args) -> int:
    """Deploy now."""
    r = ops.now(args.project, who=args.who, yes=args.yes)
    show(args, r, r["message"])
    return 0 if r.get("ok") else 1


def status(args) -> int:
    """Show deploy status."""
    r = ops.status(args.project)
    lines = [f"Live address: {r['live_url'] or 'none yet'}",
             f"Last good commit: {r['last_good_commit'][:7] or 'none yet'}"]
    lines += [f"{d['at']}  {'ok' if d['ok'] else ('rolled back' if d['rolled_back'] else 'failed')}  "
              f"{d['commit'][:7]}  {d['reason']}".rstrip() for d in r["recent"]]
    return show(args, r, "\n".join(lines))


def deployers(args) -> int:
    """List deployers."""
    r = ops.deployers()
    rows = [[d["name"], d["title"], "yes" if d["supported"] else "no", "yes" if d["preview"] else "no",
             ", ".join(d["suggested_for"])] for d in r["deployers"]]
    text = table(rows, ["deployer", "title", "supported", "preview", "suggested for"])
    return show(args, r, text + "".join(f"\nProblem: {p}" for p in r["problems"]))
