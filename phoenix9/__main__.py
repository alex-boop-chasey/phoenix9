"""The phoenix command line: builds the argparse groups and turns plain-words errors into exit codes."""
import argparse
import os
import sys

from phoenix9 import __version__
from phoenix9 import keys as keys_core
from phoenix9.cli import agent, bell, block, edit, plan, spec as spec_cmd, reply, cards, chatcmd, repair, report, search, api, deploy, doc, docs, doctor, gate, images, keys, library, models, nav, output, project, reference as reference_cmd, run, runner, service, services, settings, suggest, ui, update
from phoenix9.ops.common import OpsError

GROUPS = (reference_cmd, run, gate, bell, settings, library, project, doctor, api, service, services, keys, update, deploy, images, models, agent, block, reply, cards, doc, docs, nav, ui, chatcmd, repair, report, search, suggest, edit, plan, spec_cmd)


def build_parser() -> argparse.ArgumentParser:
    """The full parser; --json and --who work before or after the command."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print JSON (for agents)")
    common.add_argument("--who", default=argparse.SUPPRESS,
                        help="who is running this (default cli; ignored when $PHOENIX_WHO is set)")
    parser = argparse.ArgumentParser(prog="phoenix", description="Phoenix 9: project manager and build harness.",
                                     parents=[common])
    parser.add_argument("--version", action="version", version=f"phoenix {__version__}")
    sub = parser.add_subparsers(dest="group", metavar="GROUP", title="groups")
    for module in GROUPS:
        module.add(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command; exit code 0 ok, 1 refused or a problem, 2 usage error."""
    argv = sys.argv[1:] if argv is None else argv
    keys_core.load_all_secrets()   # every saved secret is scrubbed from what this process prints or logs
    if argv[:2] == ["runner", "serve"]:  # hidden: the systemd service runs this
        return runner.serve()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 2)
    args.json = getattr(args, "json", False)
    # a session started with PHOENIX_WHO (the chat and agent units set chat:<name>) keeps that name: --who
    # cannot override it, or a chat could call itself cli and do what only Alex may do
    args.who = os.environ.get("PHOENIX_WHO") or getattr(args, "who", None) or "cli"
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except OpsError as err:
        return output.problem(args, str(err))


if __name__ == "__main__":
    sys.exit(main())
