"""Command for `phoenix bell`: what needs Alex, one line each."""
from phoenix9.cli.output import show
from phoenix9.ops import bell as bell_ops, common


def add(sub, common_parser) -> None:
    """Register the bell command."""
    p = sub.add_parser("bell", parents=[common_parser], help="list what needs you (questions, failed builds, held merges, services, allowance)")
    p.set_defaults(func=run)


def run(args) -> int:
    """Show the bell list."""
    r = bell_ops.show()
    common.record_command(args.who, "bell")
    lines = [f"{i['kind']} · {i['title']} · {i['detail']}" for i in r["items"]]
    return show(args, r, "\n".join(lines) or "Nothing needs you right now.")
