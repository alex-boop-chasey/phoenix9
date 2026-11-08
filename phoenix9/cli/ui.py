"""The `phoenix ui` commands: move the open dashboard to a page."""
from phoenix9.cli.nav import _params
from phoenix9.cli.output import problem, show
from phoenix9.ops import common, ui


def add(sub, common_parser) -> None:
    """Register the ui group."""
    p = sub.add_parser("ui", parents=[common_parser], help="move the open dashboard")
    cmds = p.add_subparsers(dest="ui_cmd", metavar="COMMAND", title="commands")
    g = cmds.add_parser("go", parents=[common_parser], help="move the dashboard to a page")
    g.add_argument("to", help="the page, like projects, new, settings or p/<name>/build")
    g.add_argument("--param", action="append", default=[], metavar="K=V", help="a page option, repeatable")
    g.set_defaults(func=run_go)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_go(args) -> int:
    """Move the dashboard, or print the reason it cannot be moved."""
    try:
        found = ui.go(args.to, _params(args.param), args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, {"ok": True, **found}, f"Moved the dashboard to {found['label']}")
