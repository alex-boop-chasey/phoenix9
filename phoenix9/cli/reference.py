"""Commands for `phoenix reference`: list, add and remove a project's reference files and links."""
from pathlib import Path

from phoenix9.cli.output import problem, show, table
from phoenix9.ops import common, reference as ops


def add(sub, common_parser) -> None:
    """Register the reference group."""
    p = sub.add_parser("reference", parents=[common_parser], help="a project's reference files and links")
    cmds = p.add_subparsers(dest="reference_cmd", metavar="COMMAND", title="commands")
    c = cmds.add_parser("list", parents=[common_parser], help="show the reference files and links")
    c.add_argument("project")
    c.set_defaults(func=run_list)
    c = cmds.add_parser("add", parents=[common_parser], help="save a file as reference material")
    c.add_argument("project")
    c.add_argument("file")
    c.add_argument("--replace", action="store_true", help="overwrite a file with the same name")
    c.set_defaults(func=run_add)
    c = cmds.add_parser("remove", parents=[common_parser], help="delete one reference file")
    c.add_argument("project")
    c.add_argument("file", help="the file's name as listed")
    c.set_defaults(func=run_remove)
    c = cmds.add_parser("link", parents=[common_parser], help="save a web link as reference material")
    c.add_argument("project")
    c.add_argument("url")
    c.add_argument("--note", default="", help="a few words about the link")
    c.set_defaults(func=run_link)
    c = cmds.add_parser("unlink", parents=[common_parser], help="remove one saved link")
    c.add_argument("project")
    c.add_argument("url")
    c.set_defaults(func=run_unlink)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def _text(data: dict) -> str:
    """The files and links as two short lists."""
    files = table([[f["name"], f["kind"], f["size"], f["modified"]] for f in data["files"]],
                  ["FILE", "KIND", "BYTES", "MODIFIED"]) if data["files"] else "No reference files."
    links = "\n".join(f"{l['url']}" + (f"  ({l['note']})" if l["note"] else "") for l in data["links"]) \
        or "No reference links."
    return f"Files\n{files}\n\nLinks\n{links}"


def run_list(args) -> int:
    """Print the project's reference files and links."""
    try:
        data = ops.show(args.project)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, data, _text(data))


def run_add(args) -> int:
    """Save one file as reference material."""
    path = Path(args.file)
    try:
        data = path.read_bytes()
    except OSError as err:
        return problem(args, f"I could not read {args.file}: {err.strerror or err}")
    try:
        entry = ops.add(args.project, path.name, data, args.who, replace=args.replace)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, entry, f"Saved {entry['name']} ({entry['kind']}) as reference material for {args.project}.")


def run_remove(args) -> int:
    """Delete one reference file."""
    try:
        result = ops.remove(args.project, args.file, args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, result, f"Removed {args.file} from {args.project}'s reference material.")


def run_link(args) -> int:
    """Save one web link, with an optional note."""
    note = " ".join(args.note.split())
    text = f"{args.url} | {note}" if note else args.url
    try:
        result = ops.add_links(args.project, text, args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    said = "Saved the link." if result["added"] else "That link was already saved."
    return show(args, result, said)


def run_unlink(args) -> int:
    """Remove one saved link."""
    try:
        result = ops.remove_link(args.project, args.url, args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, result, "Removed the link.")
