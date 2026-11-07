"""The `phoenix card` command: print a card's summary line, its reply block and the fallback line."""
import json

from phoenix9 import scrub
from phoenix9.cli.output import problem, show
from phoenix9.ops import cards, common


def add(sub, common_parser) -> None:
    """Register the card command."""
    p = sub.add_parser("card", parents=[common_parser], help="make a reply block (card) for the agent to paste")
    p.add_argument("type", help="the card type: projects, gates, run or builds")
    p.add_argument("--query", help="the card's query as a JSON object")
    p.add_argument("--title", help="a title to show instead of the default")
    p.set_defaults(func=run_card)


def run_card(args) -> int:
    """Check the card against live data, then print summary, block and fallback line."""
    common.record_command(args.who, "card " + args.type)
    try:
        query = json.loads(args.query) if args.query else {}
    except ValueError:
        return problem(args, "--query is not valid JSON.")
    try:
        card = cards.build(args.type, query, args.title)
    except common.OpsError as err:
        return problem(args, str(err))
    line = scrub.scrub(cards.summary(card))
    block = cards.block(args.type, query, args.title)
    return show(args, {"summary": line, "block": block, "card": card}, "\n".join([line, block, line]))
