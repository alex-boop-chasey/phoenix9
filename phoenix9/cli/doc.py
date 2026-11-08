"""The `phoenix doc` commands: show a document by its id, or list a run's documents."""
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import common, docs


def add(sub, common_parser) -> None:
    """Register the doc group."""
    p = sub.add_parser("doc", parents=[common_parser], help="read run and notes documents")
    cmds = p.add_subparsers(dest="doc_cmd", metavar="COMMAND", title="commands")
    s = cmds.add_parser("show", parents=[common_parser], help="print a document")
    s.add_argument("id", help="the document id, like run:<run id>/plan.md or notes:<project>/<file>.md")
    s.set_defaults(func=run_show)
    ls = cmds.add_parser("list", parents=[common_parser], help="list a run's documents")
    ls.add_argument("run", help="the run id")
    ls.set_defaults(func=run_list)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_show(args) -> int:
    """Print one document's text, or the reason it cannot be shown."""
    common.record_command(args.who, "doc show " + args.id)
    try:
        doc = docs.show(args.id)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, doc, doc["text"])


def run_list(args) -> int:
    """Print a run's document ids and titles."""
    common.record_command(args.who, "doc list " + args.run)
    try:
        rows = docs.list(args.run)
    except common.OpsError as err:
        return problem(args, str(err))
    text = table([[r["id"], r["title"]] for r in rows], ["ID", "TITLE"]) if rows else "No documents."
    return show(args, rows, text)
