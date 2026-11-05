"""Commands for `phoenix services`: list, connect, test, disconnect, recipes."""
import getpass
import sys

from phoenix9 import scrub, services as lib
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import services as ops


def add(sub, common) -> None:
    """Register the services group."""
    group = sub.add_parser("services", help="connected services (Supabase, Stripe...)").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common], help="every service and whether it is connected")
    p.set_defaults(func=list_)
    p = group.add_parser("connect", parents=[common], help="save a service's account keys and check them")
    p.add_argument("name")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--from-file", metavar="PATH", help="read NAME=value lines from this file")
    source.add_argument("--from-stdin", action="store_true", help="read NAME=value lines from stdin")
    p.add_argument("--no-check", action="store_true", help="save without trying the key")
    p.set_defaults(func=connect)
    p = group.add_parser("test", parents=[common], help="try a connected service's saved key")
    p.add_argument("name")
    p.set_defaults(func=test)
    p = group.add_parser("disconnect", parents=[common], help="remove a service's account keys")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="confirm")
    p.set_defaults(func=disconnect)
    p = group.add_parser("recipes", parents=[common], help="what the library holds for each service")
    p.set_defaults(func=recipes)


def _state(row: dict) -> str:
    if row["support"] == "keys-only":
        return "no account connection needed"
    if not row["connected"]:
        return "not connected"
    return "connected, key checked OK" if row["checked"] == "ok" else f"connected, key {row['checked']}"


def list_(args) -> int:
    """List the services."""
    rows = ops.list_()
    text = "\n".join(f"{r['title']}: {_state(r)}" for r in rows)
    return show(args, rows, text)


def _parse(text: str) -> dict:
    """NAME=value lines to a dict (same rules as env files)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k] = v
    return out


def _values(args, names: list[str]) -> dict | None:
    """Values from a file, stdin or a hidden prompt; None when there is no way to ask."""
    if args.from_file:
        with open(args.from_file, encoding="utf-8") as f:
            return _parse(f.read())
    if args.from_stdin:
        return _parse(sys.stdin.read())
    if not sys.stdin.isatty():
        return None
    return {n: getpass.getpass(f"{n}: ") for n in names}


def connect(args) -> int:
    """Connect a service from a file, stdin or a prompt (never from an argument)."""
    svc = lib.get(args.name)
    names = svc["account_keys"] if svc else []
    try:
        values = _values(args, names)
    except OSError as err:
        return problem(args, f"Cannot read {args.from_file}: {err.strerror}.")
    if values is None:
        return problem(args, "Give the keys with --from-file PATH or --from-stdin, or run this in a terminal "
                             "to be asked.", 2)
    scrub.add_secrets(values.values())
    extra = {k: values.pop(k) for k in [k for k in values if k.islower()]}   # lower-case names are plain settings
    r = ops.connect(args.name, values, who=args.who, check=not args.no_check, settings_in=extra)
    return show(args, r, r["message"])


def test(args) -> int:
    """Try a connected service's saved key."""
    r = ops.test(args.name, who=args.who)
    show(args, r, r["message"])
    return 0 if r["ok"] else 1


def disconnect(args) -> int:
    """Disconnect a service."""
    r = ops.disconnect(args.name, who=args.who, yes=args.yes)
    text = f"{args.name}: disconnected." + (f"\n{r['warning']}" if r["warning"] else "")
    return show(args, r, text)


def recipes(args) -> int:
    """Show the library's recipes."""
    rows = ops.recipes()
    grid = [[r["name"], r["support"], "yes" if r["install_md"] else "no", "yes" if r["recipe_py"] else "no",
             r["allowed_calls"]] for r in rows]
    return show(args, rows, table(grid, ["SERVICE", "SUPPORT", "INSTALL.MD", "RECIPE.PY", "CALLS"]))
