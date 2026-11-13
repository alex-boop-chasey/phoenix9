"""Command for `phoenix bell`: what needs Alex, one dated line each; `phoenix bell dismiss` hides an item."""
from datetime import datetime

from phoenix9.cli.output import problem, show
from phoenix9.ops import bell as bell_ops, common


def add(sub, common_parser) -> None:
    """Register the bell command and its dismiss action."""
    p = sub.add_parser("bell", parents=[common_parser], help="list what needs you (questions, failed builds, held merges, services, allowance)")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", metavar="ACTION")
    d = actions.add_parser("dismiss", parents=[common_parser], help="hide a bell item (it shows again only as a new event)")
    d.add_argument("id", nargs="?", help="the item's id (from `phoenix bell --json`)")
    d.add_argument("--all", action="store_true", help="hide every item shown now")
    d.set_defaults(func=dismiss)


def when(stamp: str) -> str:
    """A bell item's date and time in plain words, in the server's local time."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "unknown time"


def _lines(r: dict) -> str:
    """One line per item: kind, date and time, title and detail."""
    lines = [f"{i['kind']} · {when(i['since'])} · {i['title']} · {i['detail']}" for i in r["items"]]
    return "\n".join(lines) or "Nothing needs you right now."


def run(args) -> int:
    """Show the bell list."""
    r = bell_ops.show()
    common.record_command(args.who, "bell")
    return show(args, r, _lines(r))


def dismiss(args) -> int:
    """Dismiss one item, or all of them."""
    if args.all == bool(args.id):
        return problem(args, "Give one item id, or --all.")
    try:
        r = bell_ops.dismiss_all(args.who) if args.all else bell_ops.dismiss(args.id, args.who)
    except common.OpsError as e:
        return problem(args, str(e))
    return show(args, r, "Dismissed.\n" + _lines(r))
