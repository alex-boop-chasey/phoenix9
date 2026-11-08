"""The `phoenix choice` and `phoenix confirm` commands: print a ready-made reply block and its fallback line."""
import json
import sys

from phoenix9 import scrub
from phoenix9.cli.output import problem, show
from phoenix9.ops import blocks, common


def add(sub, common_parser) -> None:
    """Register the choice and confirm commands."""
    c = sub.add_parser("choice", parents=[common_parser], help="make a phoenix-choice block for the agent to paste")
    c.add_argument("--id", required=True, help="a short id, like pick-db")
    c.add_argument("--question", required=True, help="the question to ask")
    c.add_argument("--option", action="append", default=[], metavar="KEY=LABEL[::DETAIL]",
                   help="an answer, repeatable (2 to 8)")
    c.add_argument("--mode", choices=("single", "multi"), default="single", help="pick one or several")
    c.add_argument("--recommended", metavar="KEY", help="the key of the option to suggest")
    c.add_argument("--other", action="store_true", help="also allow a free-text answer")
    c.set_defaults(func=run_choice)
    k = sub.add_parser("confirm", parents=[common_parser], help="make a phoenix-confirm block for the agent to paste")
    k.add_argument("--id", required=True, help="a short id, like del-old")
    k.add_argument("--action", required=True, help="what will happen, in plain words")
    k.add_argument("--command", required=True, help="the command that runs on yes")
    k.add_argument("--danger", action="store_true", help="mark the action as risky")
    k.set_defaults(func=run_confirm)


def _options(items: list[str], recommended: str | None) -> list[dict]:
    """Parse KEY=LABEL[::DETAIL] items; OpsError on a malformed item or unknown recommended key."""
    out = []
    for item in items:
        key, sep, rest = item.partition("=")
        label, _, detail = rest.partition("::")
        if not sep or not key or not label:
            raise common.OpsError(f"--option needs key=label[::detail], not '{item}'.")
        option = {"key": key, "label": label}
        if detail:
            option["detail"] = detail
        out.append(option)
    if recommended is not None:
        match = [o for o in out if o["key"] == recommended]
        if not match:
            raise common.OpsError(f"--recommended '{recommended}' is not one of the option keys.")
        match[0]["recommended"] = True
    return out


def _emit(args, kind: str, obj: dict, fallback: str) -> int:
    """Check the block, then print it with its fallback line (or the reason, exit 1)."""
    text = json.dumps(obj, sort_keys=True)
    result = blocks.check({"kind": kind, "json": text})
    if not result["ok"]:
        return problem(args, result["reason"])
    block = f"```phoenix-{kind}\n{text}\n```"
    fallback = scrub.scrub(fallback)
    return show(args, {"block": block, "fallback": fallback}, block + "\n" + fallback)


def run_choice(args) -> int:
    """Print a choice block and its numbered fallback line."""
    common.record_command(args.who, "choice")
    try:
        options = _options(args.option, args.recommended)
    except common.OpsError as err:
        return problem(args, str(err))
    obj = {"v": 1, "id": args.id, "question": args.question, "mode": args.mode, "options": options}
    if args.other:
        obj["other"] = True
    numbered = " ".join(f"{i}) {o['label']}" for i, o in enumerate(options, 1))
    return _emit(args, "choice", obj, f"{args.question} {numbered}")


def run_confirm(args) -> int:
    """Print a confirm block and its fallback line."""
    common.record_command(args.who, "confirm")
    obj = {"v": 1, "id": args.id, "action": args.action, "command": args.command}
    if args.danger:
        obj["danger"] = True
    return _emit(args, "confirm", obj, f"{args.action}: reply yes to run `{args.command}`")
