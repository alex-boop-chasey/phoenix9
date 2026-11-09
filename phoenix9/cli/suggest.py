"""Commands for `phoenix suggest`: list the report lines worth a mention and mark one shown, snoozed or dismissed."""
from phoenix9 import suggest
from phoenix9.cli.output import problem, show
from phoenix9.ops import common, suggest as suggest_ops

MARKS = (("shown", "shown", "say that a suggestion was mentioned to Alex"),
         ("snooze", "snoozed", "hide a suggestion for a while (default 24 hours)"),
         ("dismiss", "dismissed", "never suggest this again (until its state changes)"))


def add(sub, common_parser) -> None:
    """Register the suggest group."""
    group = sub.add_parser("suggest", help="things worth doing, from the status report").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common_parser], help="list up to 3 suggestions (needs-attention first)")
    p.add_argument("--strip", action="store_true", help="the Agent panel strip's view (also shown when the setting is strip-only)")
    p.set_defaults(func=list_)
    for name, what, text in MARKS:
        p = group.add_parser(name, parents=[common_parser], help=text)
        p.add_argument("key", help="the suggestion key from `phoenix suggest list`")
        if name == "snooze":
            p.add_argument("--hours", type=float, default=suggest.SNOOZE_HOURS, help="how long to hide it")
        p.set_defaults(func=mark, what=what)


def list_(args) -> int:
    """Show the suggestions."""
    r = suggest_ops.list_(args.strip)
    rows = r["suggestions"]
    lines = [f"{row['key']}{' (already shown)' if row['shown'] else ''}\n  {row['text']}" for row in rows]
    text = "\n".join(lines) if lines else ("Suggestions are off." if r["mode"] == "off" else "Nothing to suggest.")
    return show(args, r, text)


def mark(args) -> int:
    """Mark a suggestion."""
    try:
        r = suggest_ops.mark(args.key, args.what, args.who, getattr(args, "hours", suggest.SNOOZE_HOURS))
    except common.OpsError as e:
        return problem(args, str(e))
    return show(args, r, f"Marked {args.key} as {args.what}.")
