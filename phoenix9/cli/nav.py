"""The `phoenix nav` command: print a dashboard link, a phoenix-nav reply block and its fallback line."""
import json

from phoenix9 import routes, scrub
from phoenix9.cli.output import problem, show
from phoenix9.ops import app, common


def add(sub, common_parser) -> None:
    """Register the nav command."""
    p = sub.add_parser("nav", parents=[common_parser], help="make a link to a dashboard page for the agent to paste")
    p.add_argument("to", help="the page, like projects, new, settings or p/<name>/build")
    p.add_argument("--param", action="append", default=[], metavar="K=V", help="a page option, repeatable")
    p.add_argument("--check", action="store_true", help="only check the page exists: print ok or the reason")
    p.set_defaults(func=run_nav)


def _params(items: list[str]) -> dict:
    """K=V pairs as a dict; OpsError when one has no '='."""
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise common.OpsError(f"--param needs key=value, not '{item}'.")
        out[key] = value
    return out


def _link(url: str, hash_: str) -> str:
    """The dashboard address (no fragment, one trailing slash) followed by the hash."""
    return url.split("#", 1)[0].rstrip("/") + "/" + hash_


def run_nav(args) -> int:
    """Resolve the route, then print label, link, block and fallback line (or just ok with --check)."""
    common.record_command(args.who, "nav " + args.to)
    try:
        params = _params(args.param)
        found = routes.resolve(args.to, params)
    except common.OpsError as err:
        return problem(args, str(err))
    if args.check:
        return show(args, {"ok": True}, "ok")
    label, link = found["label"], scrub.scrub(_link(app.dashboard_url(), found["hash"]))
    link_obj = {"to": args.to, **({"params": params} if params else {}), "label": label}
    block = "```phoenix-nav\n" + json.dumps({"v": 1, "links": [link_obj]}, sort_keys=True) + "\n```"
    fallback = f"Open {label}: {link}"
    return show(args, {"label": label, "link": link, "block": block, "fallback": fallback},
                "\n".join([label, link, block, fallback]))
