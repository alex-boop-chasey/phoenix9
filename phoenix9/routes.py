"""The catalogue of dashboard pages the agent may point at, and the check that a link is real."""
import re
from urllib.parse import quote

from phoenix9 import gates, paths, runs as runs_mod, settings
from phoenix9.ops import common, docs as ops_docs, logs as ops_logs

# Same list as web/src/lib/routes.ts (a test keeps them equal); params are in hash order.
ROUTES: list[tuple[str, list[str]]] = [
    ("projects", ["q", "status", "owner", "sort", "attention"]),
    ("new", []),
    ("p/<name>/overview", ["gate"]),
    ("p/<name>/build", ["run", "wizard"]),
    ("p/<name>/logs", ["run", "step", "task", "kind", "log"]),
    ("p/<name>/settings", ["section", "key"]),
    ("settings", ["section"]),
    ("doc", ["path"]),
]
GLOBAL_SECTIONS = ("services", "models", "updates", "addresses", "logs")
PROJECT_SECTIONS = ("project", "build")
_PROJECT_ROUTE = re.compile(r"p/([^/]+)/([a-z]+)")


def _match(to: str) -> tuple[str, list[str], str | None]:
    """The catalogue name, its params and the project name for a route; OpsError when unknown."""
    found = _PROJECT_ROUTE.fullmatch(to or "")
    if found:
        generic = f"p/<name>/{found.group(2)}"
        for name, params in ROUTES:
            if name == generic:
                return name, params, found.group(1)
    for name, params in ROUTES:
        if name == to:
            return name, params, None
    raise common.OpsError(f"'{to}' is not a page Phoenix can open.")


def _hash(name: str, project: str | None, order: list[str], params: dict) -> str:
    """The URL hash for a route with its params in catalogue order, empty ones left out."""
    query = "&".join(f"{k}={quote(str(params[k]), safe='')}" for k in order if params.get(k) not in (None, ""))
    path = "/" + (f"p/{project}/{name.rsplit('/', 1)[1]}" if project else "" if name == "projects" else name)
    return f"#{path}" + (f"?{query}" if query else "")


def _check_gate(project: str, gate: str) -> None:
    if gate not in [g["id"] for g in gates.list_gates(project)]:
        raise common.NotFound(f"{project} has no open gate '{gate}'.")


def _check_run(project: str, run: str) -> None:
    if not runs_mod.RUN_ID_RE.fullmatch(run) or not (paths.runs(project) / run).is_dir():
        raise common.NotFound(f"{project} has no build '{run}'.")


def _check_wizard(value: str) -> None:
    if not value.isdigit() or not 1 <= int(value) <= 7:
        raise common.OpsError("The build wizard has slides 1 to 7.")


def _check_log(project: str, log: str) -> None:
    if log not in [e["id"] for e in ops_logs.list_(project)]:
        raise common.NotFound(f"{project} has no log '{log}'.")


def _check_key(key: str) -> None:
    if key not in settings.all_specs(common.library()):
        raise common.OpsError(f"'{key}' is not a project setting.")


def _check_section(name: str, section: str) -> None:
    allowed = GLOBAL_SECTIONS if name == "settings" else PROJECT_SECTIONS
    if section not in allowed:
        raise common.OpsError(f"'{section}' is not a settings section; use one of: {', '.join(allowed)}.")


def _check_doc(path: str) -> None:
    ops_docs.resolve(path)  # raises a plain OpsError/NotFound when the document id is wrong or missing


def _check_params(name: str, project: str | None, params: dict) -> None:
    """Refuse a param value that points at something that does not exist."""
    if params.get("gate"):
        _check_gate(project, str(params["gate"]))
    if name.endswith("/build") and params.get("wizard") not in (None, ""):
        _check_wizard(str(params["wizard"]))
    if params.get("run"):
        _check_run(project, str(params["run"]))
    if params.get("log"):
        _check_log(project, str(params["log"]))
    if params.get("key"):
        _check_key(str(params["key"]))
    if params.get("section"):
        _check_section(name, str(params["section"]))
    if name == "doc":
        _check_doc(str(params.get("path") or ""))


def _label(name: str, project: str | None, params: dict) -> str:
    """A breadcrumb like 'test-site › Settings › Build'."""
    if project:
        parts = [project, name.rsplit("/", 1)[1].capitalize()]
    else:
        parts = {"projects": ["Projects"], "new": ["New project"], "settings": ["Settings"], "doc": ["Document"]}[name]
    if params.get("section"):
        parts = parts + [str(params["section"]).capitalize()]
    return " › ".join(parts)


def resolve(to: str, params: dict | None = None) -> dict:
    """Check a route and its params against live data; return {hash, label} or raise a plain OpsError."""
    params = params or {}
    if not isinstance(params, dict):
        raise common.OpsError("Route params must be an object.")
    name, order, project = _match(to)
    unknown = sorted(set(params) - set(order))
    if unknown:
        raise common.OpsError(f"'{to}' has no param '{unknown[0]}'.")
    if project:
        common.project_dir(project)
    _check_params(name, project, params)
    return {"hash": _hash(name, project, order, params), "label": _label(name, project, params)}
