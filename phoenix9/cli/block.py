"""The `phoenix block` commands: check a reply block before the agent sends it."""
import re
import sys
from pathlib import Path

from phoenix9.cli.output import problem, show
from phoenix9.ops import blocks, common

_FENCE = re.compile(r"```\s*phoenix-(card|choice|confirm|nav)[ \t]*\n(.*?)\n[ \t]*```", re.S)


def add(sub, common_parser) -> None:
    """Register the block group."""
    p = sub.add_parser("block", parents=[common_parser], help="check reply blocks")
    cmds = p.add_subparsers(dest="block_cmd", metavar="COMMAND", title="commands")
    c = cmds.add_parser("check", parents=[common_parser], help="check one block (a fenced block or bare JSON)")
    c.add_argument("file", help="a file holding the block, or - for standard input")
    c.add_argument("--kind", choices=blocks.KINDS, help="the block kind (needed for bare JSON)")
    c.set_defaults(func=run_check)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def _split(text: str, kind: str | None) -> tuple[str | None, str]:
    """The kind and JSON text: from the fence tag when there is one, else the given kind."""
    found = _FENCE.search(text)
    if found:
        return kind or found.group(1), found.group(2)
    return kind, text.strip()


def run_check(args) -> int:
    """Read one block, check it, and print ok with what it points at, or the reason (exit 1)."""
    common.record_command(args.who, "block check")
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        return problem(args, f"Cannot read {args.file}: {err.__class__.__name__}.")
    kind, body = _split(text, args.kind)
    if kind is None:
        return problem(args, "Cannot tell the block kind: use a fenced block or give --kind.")
    result = blocks.check({"kind": kind, "json": body})
    if not result["ok"]:
        if args.json:
            show(args, result)
        else:
            print("block could not be shown: " + result["reason"], file=sys.stderr)
        return 1
    return show(args, result, "ok")
