"""Commands for `phoenix search`: find text across projects, builds, notes, research and logs."""
from phoenix9 import search as core
from phoenix9.cli.output import problem, show
from phoenix9.ops import common, search as search_ops
from phoenix9.ops.common import OpsError


def add(sub, common_parser) -> None:
    """Register the search command."""
    p = sub.add_parser("search", parents=[common_parser], help="search projects, builds, notes, research and logs")
    p.add_argument("text", help="the words to look for (2 to 100 characters)")
    p.add_argument("--kind", choices=core.KINDS, help="only this kind of result")
    p.add_argument("--limit", type=int, default=20, help="how many results at most (default 20, at most 50)")
    p.set_defaults(func=run)


def _line(item: dict) -> str:
    """One result as 'kind · title · where it is', with the snippet under it."""
    text = f"{item['kind']} · {item['title']} · {item['project']} · opens {item['page'].get('hash', '')}"
    return text + (f"\n    {item['snippet']}" if item["snippet"] else "")


def run(args) -> int:
    """Search and print the results."""
    try:
        r = search_ops.run(args.text, args.kind, args.limit)
    except OpsError as err:
        return problem(args, str(err))
    common.record_command(args.who, "search")
    text = "\n".join(_line(x) for x in r["results"]) or "Nothing found."
    return show(args, r, text)
