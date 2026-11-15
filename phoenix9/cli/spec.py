"""The `phoenix spec check <file>` command: check a spec file and list its problems."""
from pathlib import Path

from phoenix9.cli.output import problem, show
from phoenix9.ops import common, runs
from phoenix9.ops.common import OpsError


def add(sub, common_parser) -> None:
    """Register the spec group."""
    p = sub.add_parser("spec", parents=[common_parser], help="work with spec files")
    cmds = p.add_subparsers(dest="spec_cmd", metavar="COMMAND", title="commands")
    c = cmds.add_parser("check", parents=[common_parser], help="check a spec file")
    c.add_argument("file")
    c.add_argument("--preset", help="check for this preset (with the check-writer off every task needs a command)")
    c.add_argument("--project", help="check for this project's settings")
    c.set_defaults(func=run_check)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_check(args) -> int:
    """Check a spec file; exit 1 and list the problems when it is not valid."""
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as err:
        return problem(args, f"I could not read {args.file}: {err.strerror or err}")
    try:
        found = runs.check_spec(text, preset=args.preset, project=args.project)
    except OpsError as err:
        return problem(args, str(err))
    common.record_command(args.who, "spec check")
    errors = found["problems"]
    lines = ([found["basis"]] if found["basis"] else []) + (errors or ["Spec is valid."])
    show(args, {"file": args.file, **found}, "\n".join(lines))
    return 1 if errors else 0
