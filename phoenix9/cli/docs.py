"""The `phoenix docs` commands: regenerate the agent's reference files from the code."""
from phoenix9 import docsgen
from phoenix9.cli.output import show
from phoenix9.ops import common


def add(sub, common_parser) -> None:
    """Register the docs group."""
    p = sub.add_parser("docs", parents=[common_parser], help="generate the agent's reference files")
    cmds = p.add_subparsers(dest="docs_cmd", metavar="COMMAND", title="commands")
    g = cmds.add_parser("generate", parents=[common_parser], help="write commands, settings, steps, pages and cards files")
    g.add_argument("--out", help="the folder to write into (default: the phoenix-agent skill folder)")
    g.set_defaults(func=run_generate)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_generate(args) -> int:
    """Write the reference files and say where they went."""
    common.record_command(args.who, "docs generate")
    files = [str(f) for f in docsgen.generate(args.out)]
    return show(args, {"files": files}, "Wrote:\n" + "\n".join(files))
