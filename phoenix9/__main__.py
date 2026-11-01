"""The phoenix command line: builds the argparse groups and turns plain-words errors into exit codes."""
import argparse
import os
import sys

from phoenix9 import __version__
from phoenix9.cli import api, doctor, gate, keys, library, output, project, run, runner, services, settings
from phoenix9.ops.common import OpsError

GROUPS = (run, gate, settings, library, project, doctor, api, services, keys)


def build_parser() -> argparse.ArgumentParser:
    """The full parser; --json and --who work before or after the command."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print JSON (for agents)")
    common.add_argument("--who", default=argparse.SUPPRESS,
                        help="who is running this (default $PHOENIX_WHO or cli)")
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
    if argv[:2] == ["runner", "serve"]:  # hidden: the systemd service runs this
        return runner.serve()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 2)
    args.json = getattr(args, "json", False)
    args.who = getattr(args, "who", None) or os.environ.get("PHOENIX_WHO") or "cli"
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except OpsError as err:
        return output.problem(args, str(err))


if __name__ == "__main__":
    sys.exit(main())
