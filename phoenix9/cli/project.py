"""Commands for `phoenix project`: list, show, edit, remove, import, check-files, new, templates, keys and services."""
import sys

from phoenix9 import project_services
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import keys as keys_ops, projects
from phoenix9.ops.common import OpsError


def add(sub, common) -> None:
    """Register the project group."""
    group = sub.add_parser("project", help="projects").add_subparsers(dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common], help="list projects, optionally searched and filtered")
    p.add_argument("--filter", default="", metavar="TEXT", help="only projects whose name or description has this text")
    p.add_argument("--status", default="all", help="all, run, fail, idle or need")
    p.add_argument("--owner", default="all", help="all, none (no repo) or a GitHub owner")
    p.add_argument("--sort", default="name", help="name, active, size, created or modified")
    p.add_argument("--attention", action="store_true", help="put projects that need you first")
    p.set_defaults(func=list_)
    p = group.add_parser("show", parents=[common], help="show one project")
    p.add_argument("name")
    p.set_defaults(func=show_)
    p = group.add_parser("edit", parents=[common], help="change a project's description, profile or repo")
    p.add_argument("name")
    p.add_argument("--description", metavar="TEXT")
    p.add_argument("--profile")
    p.add_argument("--repo", metavar="O/N")
    p.set_defaults(func=edit_)
    p = group.add_parser("remove", parents=[common], help="take a project off Phoenix's list (keeps every file)")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="really remove it")
    p.set_defaults(func=remove_)
    p = group.add_parser("delete", parents=[common], help="delete a project entirely (--dry-run shows what would go)")
    p.add_argument("name")
    p.add_argument("--dry-run", action="store_true", help="show what would be deleted; change nothing")
    p.add_argument("--confirm", metavar="NAME", help="the project's name, typed again, to really delete it")
    p.set_defaults(func=delete_)
    p = group.add_parser("delete-repo", parents=[common], help="retry deleting the GitHub repo of a deleted project")
    p.add_argument("name")
    p.set_defaults(func=delete_repo_)
    p = group.add_parser("import", parents=[common], help="bring a removed project or an existing folder into Phoenix")
    p.add_argument("target", nargs="?", metavar="NAME|PATH")
    p.add_argument("--list", action="store_true", help="list what can be imported")
    p.set_defaults(func=import_)
    p = group.add_parser("check-files", parents=[common], help="add any missing memory files (never overwrites)")
    p.add_argument("name", nargs="?", metavar="NAME")
    p.add_argument("--all", action="store_true", help="check every project")
    p.set_defaults(func=check_files_)
    p = group.add_parser("new", parents=[common], help="create a project")
    p.add_argument("name")
    p.add_argument("--description", default="", metavar="TEXT")
    p.add_argument("--profile")
    p.add_argument("--template", metavar="T", help="a menu template (see: phoenix project templates) or a GitHub OWNER/NAME")
    p.add_argument("--repo", metavar="O/N", help="copy this GitHub repo into code/")
    p.add_argument("--code", metavar="PATH", help="use code that already lives in this folder")
    p.add_argument("--new-repo", metavar="OWNER", help="make a private GitHub repo under OWNER")
    p.add_argument("--no-new-repo", action="store_true", help="do not make a GitHub repo")
    p.add_argument("--services", metavar="a,b", default="")
    p.add_argument("--keys-file", metavar="PATH", help="a TOML file of [[key]] name/value/secret rows")
    p.set_defaults(func=new_)
    group.add_parser("templates", parents=[common], help="the templates menu").set_defaults(func=templates_)
    p = group.add_parser("keys", parents=[common], help="a project's keys (secret values are never shown)")
    p.add_argument("name")
    p.add_argument("action", nargs="?", choices=("set", "remove"))
    p.add_argument("key", nargs="?", metavar="NAME")
    p.add_argument("--secret", action="store_true", help="with set: the value is secret")
    p.add_argument("--from-file", metavar="PATH", help="with set: read the value from this file (else stdin)")
    p.add_argument("--yes", action="store_true", help="with remove: really delete")
    p.set_defaults(func=keys_)
    p = group.add_parser("services", parents=[common], help="a project's services")
    p.add_argument("name")
    p.add_argument("--set", metavar="a,b", help="choose these services (empty text for none)")
    p.set_defaults(func=services_)


def _size(n) -> str:
    """Bytes in short words; '…' when not measured yet."""
    if n is None:
        return "…"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def list_(args) -> int:
    """List projects."""
    filtered = (args.filter, args.status, args.owner, args.sort, args.attention) != ("", "all", "all", "name", False)
    if filtered:
        r = projects.query(args.filter, args.status, args.owner, args.sort, args.attention)
        found = r["top"] + r["rest"]
    else:
        found = projects.list()
    text = table([[p["name"], p["harness"], _size(p["size"]), p["last_used"]] for p in found],
                 ["project", "harness", "size", "last used"]) if found else ("No projects match." if filtered else "No projects yet.")
    return show(args, found if not filtered or not args.json else r, text)


def show_(args) -> int:
    """Show one project."""
    p = projects.show(args.name)
    lines = [p["name"], f"  path: {p['path']}", f"  about: {p['description'] or '(none)'}",
             f"  repo: {p['repo'] or '(none)'}", f"  profile: {p['profile'] or '(none)'}",
             f"  services: {', '.join(p['services']) or '(none)'}", f"  size: {_size(p['size'])}",
             f"  last used: {p['last_used']}", f"  harness: {p['harness']}",
             f"  VS Code: {p['vscode_url'] or (p.get('vscode') or {}).get('reason') or 'not set'}"]
    if p["gates"]:
        lines += ["  needs you:"] + [f"    {g['id']}: {g['title']}" for g in p["gates"]]
    if p["changelog"]:
        lines += ["  recent changes:"] + [f"    {x}" for x in p["changelog"]]
    return show(args, p, "\n".join(lines))


def edit_(args) -> int:
    """Change a project's description, profile or repo."""
    r = projects.edit(args.name, args.who, args.description, args.profile, args.repo)
    return show(args, r, f"Changed {', '.join(r['changed'])} for {args.name}.")


def remove_(args) -> int:
    """Remove a project from Phoenix (needs --yes); nothing is deleted."""
    if not args.yes:
        return problem(args, f"This takes {args.name} off Phoenix's list. "
                             "Its files stay. Run it again with --yes to do it.")
    r = projects.remove(args.name, args.who)
    return show(args, r, f"Removed {args.name} from Phoenix. {r['kept']} "
                         f"Bring it back with: phoenix project import {args.name}")


def plan_text(p: dict) -> str:
    """The delete plan in plain English."""
    lines = [f"Deleting {p['name']} would remove:",
             f"  Folder: {p['folder']} ({_size(p['size'])})",
             f"  GitHub repo: {p['repo'] or '(none)'}"]
    if p["repo"] and p.get("repo_delete"):
        lines.append(f"    {p['repo_delete']['why']}")
    if p.get("open_prs_note"):
        lines.append(f"    {p['open_prs_note']}")
    lines.append(f"  Open merge requests: {len(p['open_prs'])}")
    lines += [f"    #{r['number']} {r['title']} {r['url']}" for r in p["open_prs"]]
    lines.append(f"  Commits never pushed: {p['unpushed']}")
    lines.append(f"  Builds: {p['runs']['count']}")
    lines.append(f"  Saved keys: {', '.join(p['keys']) or '(none)'}")
    lines.append(f"  Chat: {p['chat']['unit']} ({p['chat']['state']})")
    lines.append(f"  Safety copy goes under: {p['safety_copy']}")
    for d in p["deployments"]:
        lines.append(f"  Deployment {d['target']}: {d['note']}")
        lines += [f"    {u}" for u in d["links"]]
    if p["refusals"]:
        lines.append("Refused:")
        lines += [f"  {r}" for r in p["refusals"]]
    return "\n".join(lines)


def delete_(args) -> int:
    """Show the delete plan (--dry-run), or delete the project entirely (--confirm <name>)."""
    try:
        if args.dry_run:
            r = projects.delete_plan(args.name, args.who)
            return show(args, r, plan_text(r))
        if args.confirm != args.name:
            return problem(args, f"This deletes {args.name} for good. Run it with --dry-run to see what goes, "
                                 f"then again with --confirm {args.name} to do it.")
        r = projects.delete(args.name, args.confirm, args.who)
    except OpsError as e:
        return problem(args, str(e))
    return show(args, r, result_text(r))


def result_text(r: dict) -> str:
    """A delete result in plain English: each step, what was not done, what is still live."""
    lines = [f"Safety copy: {r['backup']}"]
    lines += [f"{'Kept' if s.get('kept') else 'Done' if s['ok'] else 'FAILED'}: {s['step']}. {s['words']}"
              for s in r["steps"]]
    if r["not_done"]:
        lines.append("Not done:")
        lines += [f"  {n['what']} {n['how']}" if n["how"] != n["what"] else f"  {n['what']}" for n in r["not_done"]]
    else:
        lines.append(f"{r['name']} is deleted.")
    live = r.get("still_live") or []
    if live:
        lines.append("Still live, take it down yourself:")
        for d in live:
            lines.append(f"  {d['target']}: {d['note']}")
            lines += [f"    {u}" for u in d["links"]]
    return "\n".join(lines)


def delete_repo_(args) -> int:
    """Retry only the GitHub repo delete of a project that is already deleted."""
    try:
        r = projects.delete_repo(args.name, args.who)
    except OpsError as e:
        return problem(args, str(e))
    return show(args, r, result_text(r))


def import_(args) -> int:
    """Import a project, or list what can be imported."""
    if args.list or not args.target:
        found = projects.import_candidates()
        rows = [[c["name"], c["path"], c["repo"] or "(none)", f"removed on {c['removed_on']}" if c["removed_on"] else "not listed"]
                for c in found]
        return show(args, found, table(rows, ["name", "path", "repo", "status"]) if rows else "Nothing to import.")
    r = projects.import_(args.target, args.who)
    text = f"Imported {r['name']}. It is back on Phoenix's list."
    if r.get("chat_message"):
        text += " (" + r["chat_message"] + ")"
    return show(args, r, text)


def check_files_(args) -> int:
    """Add the memory files each project is missing and say what was added."""
    if bool(args.name) == bool(args.all):
        return problem(args, "Give a project name, or --all for every project.")
    results = projects.check_files(None if args.all else args.name, args.who)
    lines = [f"{r['name']}: " + ("added " + ", ".join(r["added"]) if r["added"] else "nothing missing") for r in results]
    return show(args, results, "\n".join(lines) if lines else "No projects.")


def new_(args) -> int:
    """Create a project, printing one line per creation step."""
    opts = {"name": args.name, "description": args.description, "profile": args.profile, "template": args.template,
            "repo": args.repo, "code": args.code, "new_repo": args.new_repo, "no_new_repo": args.no_new_repo,
            "services": [x.strip() for x in args.services.split(",") if x.strip()], "keys_file": args.keys_file}
    say = None if args.json else (lambda line: print(f"- {line}"))
    r = projects.new(opts, args.who, say)
    return show(args, r, f"Created {r['path']}")


def templates_(args) -> int:
    """List the templates menu."""
    menu = projects.templates_menu()
    text = table([[t["name"], t["title"], t["profile"], t["kind"]] for t in menu],
                 ["template", "title", "profile", "kind"]) if menu else "No templates."
    return show(args, menu, text)


def _value(args) -> str:
    """The key value from --from-file or stdin (one trailing newline dropped); never from an argument."""
    if args.from_file:
        try:
            text = open(args.from_file, encoding="utf-8").read()
        except OSError as err:
            raise OpsError(f"Cannot read {args.from_file}: {err.strerror}") from None
    else:
        text = sys.stdin.read()
    return text[:-1] if text.endswith("\n") else text


def keys_(args) -> int:
    """List, set or remove a project's keys."""
    if args.action is None:
        rows = keys_ops.list_(args.name, args.who)
        shown = [[r["name"], "secret" if r["secret"] else "plain",
                  ("••••••" if r["secret"] else r["value_if_not_secret"]) if r["has_value"] else "(empty)"] for r in rows]
        return show(args, rows, table(shown, ["key", "kind", "value"]) if rows else "No keys yet.")
    if not args.key:
        return problem(args, "Say which key, for example: phoenix project keys NAME set API_KEY --secret", 2)
    if args.action == "set":
        r = keys_ops.set_(args.name, args.key, _value(args), args.secret, args.who)
        return show(args, r, f"Saved {args.key} for {args.name}.")
    if not args.yes:
        return problem(args, f"This deletes the key {args.key}. Run it again with --yes to do it.")
    r = keys_ops.remove(args.name, args.key, args.who)
    return show(args, r, f"Removed {args.key} from {args.name}.")


def services_(args) -> int:
    """List the project's services, or choose them with --set."""
    if args.set is not None:
        names = [n.strip() for n in args.set.split(",") if n.strip()]
        r = project_services.set_services(args.name, names, args.who)
        return show(args, r, f"{args.name} now uses: {', '.join(names) or 'no services'}.")
    r = project_services.overview(args.name)
    text = (f"Chosen: {', '.join(r['chosen']) or '(none)'}\nAvailable: "
            + ", ".join(f"{a['name']} ({a['title']})" for a in r["available"]))
    return show(args, r, text)
