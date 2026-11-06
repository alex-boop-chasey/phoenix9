"""The `phoenix service restart api|runner` command: restart one of Phoenix's own services safely."""
from phoenix9 import doctor
from phoenix9.cli.output import problem, show
from phoenix9.ops import service as ops


def add(sub, common) -> None:
    """Register the service group."""
    group = sub.add_parser("service", help="Phoenix's own services (phoenix-api, phoenix-runner)").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("restart", parents=[common],
                         help="restart api or runner (the runner waits for builds to reach a task boundary)")
    p.add_argument("name", choices=sorted(ops.UNITS), help="api or runner")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=restart)


def restart(args) -> int:
    """Restart a service, then print the quick doctor report (exit 0 once restarted; the report shows any problem)."""
    if not args.yes:
        return problem(args, f"This restarts {ops.UNITS[args.name]}. Add --yes to go ahead.")
    say = (lambda line: None) if args.json else print
    r = ops.restart(args.name, who=args.who, yes=True, say=say)
    return show(args, r, f"Restarted {r['service']}.\n" + doctor.render(r["doctor"]))
