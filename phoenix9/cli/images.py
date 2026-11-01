"""The `phoenix images build` command: build the step images."""
from phoenix9.cli.output import show
from phoenix9.ops import common
from phoenix9.ops import images as ops_images


def add(sub, common_parser) -> None:
    """Register images."""
    p = sub.add_parser("images", help="step images")
    verbs = p.add_subparsers(dest="verb", metavar="COMMAND", required=True)
    b = verbs.add_parser("build", parents=[common_parser], help="build the step images")
    b.add_argument("--profile", action="append", default=[], metavar="P",
                   help="build this profile (repeatable; 'base' builds the base image)")
    b.add_argument("--all", action="store_true", help="every profile and the base image")
    b.add_argument("--changed", action="store_true", help="only images whose files changed since they were built")
    b.set_defaults(func=build)


def build(args) -> int:
    """Build images; exit 1 when any build failed."""
    common.record_command(args.who, "images build")
    say = (lambda line: None) if args.json else print
    data = ops_images.build(args.profile, args.all, args.changed, say=say)
    n = len(data["built"])
    summary = "Nothing needed building." if not n else (
        f"Built {n} image{'s' if n != 1 else ''}." if data["ok"] else "At least one build failed.")
    show(args, data, summary)
    return 0 if data["ok"] else 1
