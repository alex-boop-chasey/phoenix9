"""Commands for `phoenix update`: status, install, rollback, log and release."""
from phoenix9.cli.output import show
from phoenix9.ops import common, update as ops

POLL_S = 5
GOOD = ("installed", "rolled-back-manual")


def add(sub, common_args) -> None:
    """Register the update group."""
    group = sub.add_parser("update", help="update Phoenix 9 itself").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("status", parents=[common_args], help="installed and newest version")
    p.add_argument("--refresh", action="store_true", help="ask GitHub for the newest version")
    p.set_defaults(func=status)
    p = group.add_parser("install", parents=[common_args], help="install a version (default: the newest)")
    p.add_argument("tag", nargs="?", help="a release tag like v9.2")
    p.add_argument("--yes", action="store_true", help="go ahead")
    p.add_argument("--wait", action="store_true", help="wait until the update is finished")
    p.set_defaults(func=install)
    p = group.add_parser("rollback", parents=[common_args], help="go back to the previous version")
    p.add_argument("--yes", action="store_true", help="go ahead")
    p.add_argument("--wait", action="store_true", help="wait until the rollback is finished")
    p.set_defaults(func=rollback)
    p = group.add_parser("log", parents=[common_args], help="the updater log")
    p.add_argument("--lines", type=int, default=200)
    p.set_defaults(func=log)
    p = group.add_parser("release", parents=[common_args], help="tag the current main as a new release")
    p.add_argument("--yes", action="store_true", help="go ahead")
    p.set_defaults(func=release)


def _tag(version) -> str:
    """A version dict's tag, or empty."""
    return (version or {}).get("tag") or ""


def status_text(st: dict) -> str:
    """One plain sentence about the installed version, the newest one and the harness."""
    installed = _tag(st.get("installed"))
    if not installed:
        return "Phoenix 9 is not installed yet."
    out = f"Installed {installed}"
    if st.get("previous"):
        out += f" (previous {_tag(st['previous'])})"
    newest = st.get("newest")
    if not newest:
        out += ". Newest version not checked yet."
    else:
        out += f". Newest {newest}: " + ("update available." if st.get("update_available") else "up to date.")
    if st.get("running"):
        out += " An update is running" + (f" ({st['waiting']})." if st.get("waiting") else ".")
    else:
        out += " Harness busy: " + st["busy_reason"] + "." if st.get("busy") else " Harness idle."
    return out


def status(args) -> int:
    """Show the update status."""
    st = ops.status(args.refresh)
    return show(args, st, status_text(st))


def _result_line(st: dict) -> str:
    """The last result as a sentence."""
    last = st.get("last") or {}
    line = f"{last.get('action', 'update')} {last.get('tag') or ''}: {last.get('result', 'unknown')}".replace("  ", " ")
    return line + (f" - {last['reason']}" if last.get("reason") else "")


def _wait(args, queued: dict) -> int:
    """Poll status every 5 seconds until the updater stops, then print the result."""
    clock = common.make_adapters().clock
    clock.sleep(1)      # let the unit take the lock
    while ops.status(False).get("running"):
        clock.sleep(POLL_S)
    st = ops.status(False)
    ok = (st.get("last") or {}).get("result") in GOOD
    show(args, {**queued, "last": st.get("last"), "ok": ok}, _result_line(st))
    return 0 if ok else 1


def _queued(args, out: dict, words: str) -> int:
    """Report a queued update, and wait for it when asked."""
    if getattr(args, "wait", False):
        return _wait(args, out)
    return show(args, out, words)


def install(args) -> int:
    """Queue an install."""
    out = ops.install(args.tag, args.who, args.yes)
    return _queued(args, out, f"Installing {out['tag']} has started. Check with `phoenix update status`.")


def rollback(args) -> int:
    """Queue a rollback."""
    out = ops.rollback(args.who, args.yes)
    return _queued(args, out, "Rolling back has started. Check with `phoenix update status`.")


def log(args) -> int:
    """Print the updater log tail."""
    r = ops.log(args.lines)
    text = "\n".join(r["lines"]) or "The updater log is empty."
    if r["checks_file"]:
        text += f"\nLast checks output: {r['checks_file']}"
    return show(args, r, text)


def release(args) -> int:
    """Tag main as a release."""
    r = ops.release(args.who, args.yes)
    words = (f"Tagged {r['tag']} at {r['sha'][:10]}." if r["created"]
             else f"main is already tagged {r['tag']}; nothing to do.")
    return show(args, r, words)
