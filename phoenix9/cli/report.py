"""Commands for `phoenix report`: write the plain-English status report."""
from phoenix9.cli.output import show
from phoenix9.ops import common, report as report_ops


def add(sub, common_parser) -> None:
    """Register the report group."""
    group = sub.add_parser("report", help="plain-English reports").add_subparsers(dest="action", metavar="ACTION", required=True)
    p = group.add_parser("status", parents=[common_parser], help="write and show the status report (what needs you)")
    p.add_argument("--out", help="write the report to this file instead of HOME/reports/status.md")
    p.set_defaults(func=status)
    d = group.add_parser("daily", parents=[common_parser], help="show the newest daily report (--now builds one without sending it)")
    d.add_argument("--now", action="store_true", help="build a report right now; nothing is sent or saved")
    d.set_defaults(func=daily)


def status(args) -> int:
    """Write the status report and show it."""
    r = report_ops.status(args.out)
    common.record_command(args.who, "report status")
    return show(args, {"ok": True, **r}, r["text"] + f"\nWritten to {r['path']}")


def daily(args) -> int:
    """Show the newest daily report, or a fresh one with --now."""
    r = report_ops.daily_now() if args.now else report_ops.daily_latest()
    common.record_command(args.who, "report daily --now" if args.now else "report daily")
    return show(args, {"ok": True, **r}, r["text"])
