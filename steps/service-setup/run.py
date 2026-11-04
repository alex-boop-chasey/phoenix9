"""Service setup: check the project's chosen services once (keys, hosts, recipe) and write notes for the Builder."""
import importlib.util
from pathlib import Path

from phoenix9 import atomic, keys, paths, project, project_services, reports, services, state, summary
from phoenix9.stepctx import StepResult

KEYS_WHERE = "Project → Settings → Keys, or `phoenix project keys {name} set KEY`"


def _done_names(meta: dict) -> set:
    """Names of services already set up (entries are {"name", ...} or plain strings in older files)."""
    return {e.get("name") if isinstance(e, dict) else e for e in meta.get("services_set_up") or []}


def _missing_keys(ctx, svc) -> list[str]:
    """Expected project keys of the service that have no value yet (names only)."""
    have = {k["name"]: k["has_value"] for k in keys.list_keys(ctx.project.name)}
    return [k["name"] for k in svc["project_keys"] if not have.get(k["name"])]


def _allow_hosts(ctx, chosen: list, lib: dict) -> None:
    """Add service hosts missing from the project's [domains] allow (file and this run's settings)."""
    allow = ctx.project.settings.setdefault("domains", {}).setdefault("allow", [])
    wanted = [h for n in chosen for h in lib[n]["hosts"]]
    missing = [h for h in dict.fromkeys(wanted) if h not in allow]
    if not missing:
        return
    project_services.set_services(ctx.project.name, project_services.chosen(ctx.project.name), who="runner")
    allow.extend(missing)
    ctx.log(f"added to the project's allowed hosts: {', '.join(missing)}")


def _load_recipe(name: str):
    """Import services/<name>/recipe.py, or None when the service has none."""
    path = paths.library() / "services" / name / "recipe.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"phoenix_recipe_{name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wire(ctx, name: str, svc: dict) -> str:
    """Run the service's recipe; returns a failure reason, or "" when it worked or there is none."""
    try:
        recipe = _load_recipe(name)
        if recipe is None:
            return ""
        result = recipe.wire(ctx, svc, ctx.proxies.get(name)) or {}
    except Exception as err:
        return f"{svc['title']} setup failed: {type(err).__name__}: {(str(err).splitlines() or [''])[0]}"
    if result.get("note"):
        ctx.log(f"{svc['title']}: {result['note']}")
    if result.get("ok", True):
        return ""
    return f"{svc['title']} setup failed: {result.get('reason', 'no reason given')}"


def _record(ctx, newly: list) -> None:
    """Add the newly wired services to project.json services_set_up (other fields stay)."""
    if not newly:
        return
    entries = list(project._meta(ctx.project.dir).get("services_set_up") or [])
    name = summary.facts(ctx.run.folder)["title"]
    entries += [{"name": n, "at": state.now(), "run": ctx.run.id, "run_name": name} for n in newly]
    project._save_meta(ctx.project.dir, services_set_up=entries)


def _notes(chosen: list, lib: dict) -> str:
    """services.md text: per service the title, the env var names to read, and its install notes."""
    out = ["# Services this project uses", ""]
    for name in chosen:
        svc = lib[name]
        out += [f"## {svc['title']}", ""]
        names = [k["name"] for k in svc["project_keys"]]
        if names:
            out += ["Read these environment variables in the code (never write their values anywhere):",
                    *[f"- `{n}`" for n in names], ""]
        install = paths.library() / "services" / name / "install.md"
        if install.is_file():
            out += [install.read_text(encoding="utf-8").strip(), ""]
    return "\n".join(out)


def _keys_gate(missing: dict, lib: dict, project_name: str) -> StepResult:
    """A human-task gate listing the missing key names per service."""
    lines = [f"{lib[n]['title']}: {', '.join(names)}" for n, names in missing.items()]
    why = ("These keys have no value yet. " + "; ".join(lines) + ". Paste them in "
           + KEYS_WHERE.format(name=project_name) + ", then press Done.")
    return StepResult("gate", gate={"kind": "human-task", "title": f"Paste keys for {', '.join(lib[n]['title'] for n in missing)}",
                                    "why": why, "actions": ["done", "skip", "stop"]})


def run(ctx) -> StepResult:
    """Check each chosen service in order and pass, fail, or ask for missing keys."""
    chosen = list(ctx.project.settings.get("services") or [])
    if not chosen:
        return StepResult("pass", produces={"service-notes": reports.NO_SERVICES_TEXT})
    lib = services.load_library()
    unknown = [n for n in chosen if n not in lib]
    if unknown:
        return StepResult("fail", [f"Service {n} is not in Phoenix's services library" for n in unknown])
    _allow_hosts(ctx, chosen, lib)
    missing = {n: m for n in chosen if (m := _missing_keys(ctx, lib[n]))}
    if missing and (ctx.answer or {}).get("action") == "done":
        return StepResult("fail", [f"{lib[n]['title']} still has no value for: {', '.join(m)}" for n, m in missing.items()])
    if missing:
        return _keys_gate(missing, lib, ctx.project.name)
    done = _done_names(project._meta(ctx.project.dir))
    todo = [n for n in chosen if n not in done]
    failures = [r for n in todo if (r := _wire(ctx, n, lib[n]))]
    if failures:
        return StepResult("fail", failures)
    _record(ctx, todo)
    path = ctx.run.folder / "services.md"
    atomic.write_text(path, _notes(chosen, lib))
    return StepResult("pass", produces={"service-notes": str(path)})
