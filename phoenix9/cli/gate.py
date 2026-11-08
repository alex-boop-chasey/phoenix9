"""Commands for `phoenix gate`: list open questions and answer one."""
from phoenix9.cli.output import show, table
from phoenix9.ops import gates

ACTIONS = ("approve", "back", "skip", "stop", "acknowledged", "raise")


def add(sub, common) -> None:
    """Register the gate group."""
    group = sub.add_parser("gate", help="questions waiting for you").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common], help="list open questions")
    p.add_argument("project", nargs="?")
    p.set_defaults(func=list_)
    p = group.add_parser("review", parents=[common], help="read a merge before answering")
    p.add_argument("gate_id")
    p.set_defaults(func=review)
    p = group.add_parser("answer", parents=[common], help="answer a question")
    p.add_argument("gate_id")
    p.add_argument("answer", choices=ACTIONS)
    p.add_argument("--note", default="", help="words for the step (needed for 'back')")
    p.add_argument("--by", type=float, default=None, help="dollars to add to the cap (for 'raise')")
    p.set_defaults(func=answer)


def list_(args) -> int:
    """List open gates."""
    found = gates.list(args.project)
    text = table([[g["id"], g["kind"], g["title"]] for g in found], ["gate", "kind", "title"]) \
        if found else "Nothing is waiting for you."
    return show(args, found, text)


def answer(args) -> int:
    """Answer a gate."""
    r = gates.answer(args.gate_id, args.answer, note=args.note, who=args.who, by=args.by)
    return show(args, r, f"Answered {args.gate_id}: {args.answer}.")


def review(args) -> int:
    """Show the merge review of a merge gate."""
    r = gates.review(args.gate_id)
    t = r["tasks"]
    lines = [r["title"], f"Tasks passed: {t['passed']} of {t['total']}", f"Full suite: {r['full_suite']['status']}",
             "Changes safety code: " + (", ".join(r["safety"]["files"]) if r["safety"]["flag"] else "no"),
             f"Changed files ({len(r['files'])}): +{r['added']} -{r['removed']}"]
    lines += [f"  {f['path']}  +{f['added']} -{f['removed']}" + ("  [safety]" if f["safety"] else "") for f in r["files"]]
    return show(args, r, "\n".join(lines))
