"""The dashboard API server: JSON under /api, the built web app as static files, nothing else."""
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from phoenix9 import paths, scrub
from phoenix9.api import stream
from phoenix9.ops import app, common, deploy, doctor as ops_doctor, gates, github, keys, library, logs, projects, runs, services, settings, update

MAX_BODY = 64 * 1024
DEFAULT_ORIGINS = "https://files.rebirthwebdesign.com.au"
SERVER_ERROR = "Something went wrong; details are in the API log."
NOT_BUILT = (b"<!doctype html><html><head><meta charset=utf-8><title>Phoenix 9</title></head><body>"
             b"<p>The dashboard is not built yet. Run: pnpm -C web build</p></body></html>")

# Same rule `phoenix project new` uses (phoenix9/project.py NAME_RE).
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+$")
GATE_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+\.\d+$")  # <run-id>.<n> (used by the gate routes in step 03)


JOB_KEEP_SECONDS = 3600
CREATE_BUSY = "Another project is being created; try again in a moment."
DEPLOY_BUSY = "Another deploy is running; try again when it has finished."
WHO = "dashboard"


class BadRequest(Exception):
    """The request itself is wrong (answered 400 before any ops call)."""


class NeedsConfirm(Exception):
    """A change that needs `"confirm": true` in the body (answered 409 with needs_confirm)."""


def allowed_origins() -> list[str]:
    """The origins allowed to POST, read from the environment on each request."""
    raw = os.environ.get("PHOENIX_API_ORIGINS") or DEFAULT_ORIGINS
    return [o.strip() for o in raw.split(",") if o.strip()]


def api_log(text: str) -> None:
    """Append one scrubbed line to HOME/logs/api.log (never fails the request)."""
    try:
        paths.logs().mkdir(parents=True, exist_ok=True)
        with open(paths.logs() / "api.log", "a", encoding="utf-8") as f:
            f.write(scrub.scrub(text).rstrip("\n") + "\n")
    except OSError:
        pass


def check_name(name: str) -> str:
    """A valid project name, or BadRequest."""
    if not NAME_RE.match(name):
        raise BadRequest("That isn't a valid project name.")
    return name


def check_run_id(run_id: str) -> str:
    """A valid run id, or BadRequest."""
    if not RUN_ID_RE.match(run_id):
        raise BadRequest("That isn't a valid run id.")
    return run_id


def int_param(req, key: str, default: int) -> int:
    """A whole-number query parameter, or BadRequest."""
    raw = req.query.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        raise BadRequest(f"'{key}' should be a whole number.")


# ---- GET handlers: parse, call one ops function, return the data ----

def get_info(req):
    """Reply with the app info."""
    return app.info(req.server.tag)


def get_health(req):
    """Reply that the server is up (version and tag only; no ops call that can fail)."""
    import phoenix9
    return {"ok": True, "version": phoenix9.__version__, "tag": req.server.tag}


def get_update(req):
    """Reply with the updater status; ?refresh=1 asks GitHub for the newest tag first."""
    return update.status(refresh=req.query.get("refresh") in ("1", "true"))


def get_update_log(req):
    """Reply with the tail of the updater log."""
    return update.log(min(max(int_param(req, "lines", 200), 1), 2000))


def get_deploys(req, name):
    """Reply with a project's recent deploys and live address."""
    return deploy.status(check_name(name))


def get_projects(req):
    """Reply with the project rows; with search/filter parameters, {top, rest, total, counts} instead."""
    keys = ("q", "status", "owner", "sort", "attention")
    if not any(k in req.query for k in keys):
        return projects.rows()
    attention = req.query.get("attention", "")
    if attention not in ("", "0", "1", "true", "false"):
        raise BadRequest("'attention' should be 1 or 0.")
    return projects.query(q=req.query.get("q", ""), status=req.query.get("status") or "all",
                          owner=req.query.get("owner") or "all", sort=req.query.get("sort") or "name",
                          attention=attention in ("1", "true"))


def get_check_name(req):
    """Say whether a new project name is usable."""
    return projects.check_name(req.query.get("name", ""))


def get_project(req, name):
    """Reply with one project's details."""
    row = projects.row(check_name(name))
    return {**projects.show(name), **{k: row[k] for k in ("repo_url", *projects.STATE_KEYS)}}


def get_changelog(req, name):
    """Reply with a project's recent changelog lines."""
    return projects.changelog(check_name(name), limit=int_param(req, "limit", 20))


def get_keys(req, name):
    """Reply with a project's keys, values hidden."""
    return keys.rows(check_name(name))


def get_settings(req, name):
    """Reply with a project's settings."""
    return settings.show(check_name(name))


def get_explain(req, name):
    """Reply with the plain-words explanation of a project's settings."""
    return settings.explain(check_name(name))


def get_specs(req, name):
    """Reply with a project's spec files."""
    return projects.specs(check_name(name))


def get_builds(req, name):
    """Reply with a project's builds."""
    return runs.builds(check_name(name))


def get_run(req, project, run_id):
    """Reply with one run's detail."""
    return runs.detail(check_name(project), check_run_id(run_id))


def get_gates(req):
    """Reply with the open and answered gates."""
    name = req.query.get("project")
    return gates.list_(check_name(name) if name else None)


def get_events_recent(req):
    """Reply with recent events for polling."""
    after = req.query.get("after")
    limit = min(max(int_param(req, "limit", 200), 1), 1000)
    project = req.query.get("project")
    return stream.recent(check_name(project) if project else None, int_param(req, "after", 0) if after else None, limit)


def need_project(req) -> str:
    """The project query parameter (required, valid name)."""
    return check_name(req.query.get("project") or "")


def get_logs(req):
    """Reply with the list of log files."""
    task = req.query.get("task")
    return logs.list_(need_project(req), run=req.query.get("run") or None,
                      task=int_param(req, "task", 0) if task not in (None, "") else None,
                      step=req.query.get("step") or None, kind=req.query.get("kind") or None)


def get_logs_read(req):
    """Reply with one log's scrubbed text."""
    return logs.read(need_project(req), req.query.get("id") or "")


def get_steps(req):
    """Reply with the step library."""
    return library.steps()


def get_profiles(req):
    """Reply with the profile library."""
    return library.profiles()


def get_presets(req):
    """Reply with the preset library."""
    return library.presets()


def get_templates(req):
    """Reply with the templates menu."""
    return projects.templates_menu()


def get_services_lib(req):
    """Reply with the services library."""
    return library.services()


def get_tools_lib(req):
    """Reply with the tools a step may use."""
    return library.tools()


def get_repos(req):
    """Reply with the GitHub repos Phoenix can see."""
    return github.repos()


def get_global_services(req):
    """Reply with the rows of Phoenix settings > Services (Claude, the library services, Telegram)."""
    rows = services.list_global()
    for row in rows:
        row["endpoints"] = {"connect": f"services/{row['name']}/connect",
                            "disconnect": f"services/{row['name']}/disconnect",
                            "test": f"services/{row['name']}/test"}
    return {"supported": True, "services": rows}


def get_doctor(req):
    """Run the health checks (?mode=quick by default, or full) and reply with the results."""
    mode = req.query.get("mode") or "quick"
    if mode not in ("quick", "full"):
        raise BadRequest("'mode' should be quick or full.")
    out = ops_doctor.run(mode=mode)
    out["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def get_update_history(req):
    """Reply with the updater's past installs and roll-backs, newest first."""
    return {"history": update.history()}


def get_global(req):
    """Reply with the global settings view."""
    return app.global_view()


def get_services(req):
    """Reply with every service and its connection state."""
    rows = services.list_()
    for row in rows:
        row["endpoints"] = {"connect": f"services/{row['name']}/connect",
                            "disconnect": f"services/{row['name']}/disconnect"}
    return {"supported": True, "services": rows}


def get_keys_audit(req):
    """Reply with the keys audit (names and problems only)."""
    return keys.audit()


# ---- POST handlers: check the shape of the body, call one ops function ----

def body_dict(req, key: str, default=None) -> dict:
    """An object field of the body (BadRequest when it is something else)."""
    value = req.body.get(key, default if default is not None else {})
    if not isinstance(value, dict):
        raise BadRequest(f"'{key}' should be an object.")
    return value


def body_text(req, key: str, required: bool = True):
    """A text field of the body (None when absent and not required)."""
    value = req.body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise BadRequest(f"'{key}' should be text" + (" and not empty." if required else "."))
    return value


def create_opts(body: dict) -> dict:
    """Map the create form onto the opts dict ops.projects.new takes (shapes only; ops checks the rules)."""
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise BadRequest("The form needs a project name.")
    description = body.get("description", "")
    profile = body.get("profile")
    source = body.get("source") or {"kind": "empty"}
    new_repo = body.get("new_repo") or {"on": False}
    services = body.get("services") or []
    key_rows = body.get("keys") or []
    if not isinstance(description, str):
        raise BadRequest("'description' should be text.")
    if profile is not None and not isinstance(profile, str):
        raise BadRequest("'profile' should be text.")
    if not isinstance(source, dict) or source.get("kind") not in ("empty", "repo", "template", "code"):
        raise BadRequest("'source.kind' should be empty, repo, template or code.")
    if not isinstance(new_repo, dict):
        raise BadRequest("'new_repo' should be an object.")
    if not isinstance(services, list) or not all(isinstance(x, str) for x in services):
        raise BadRequest("'services' should be a list of names.")
    if not isinstance(key_rows, list) or not all(
            isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance(r.get("value"), str)
            and isinstance(r.get("secret", True), bool) for r in key_rows):
        raise BadRequest("'keys' should be a list of {name, value, secret}.")
    kind = source["kind"]
    field = {"repo": "repo", "template": "template", "code": "path"}.get(kind)
    if field and (not isinstance(source.get(field), str) or not source[field]):
        raise BadRequest(f"'source.{field}' should be text.")
    owner = new_repo.get("owner") if new_repo.get("on") else None
    if new_repo.get("on") and (not isinstance(owner, str) or not owner):
        raise BadRequest("'new_repo.owner' should be text.")
    opts = {"name": name, "description": description, "profile": profile or None, "services": services,
            "keys": [{"name": r["name"], "value": r["value"], "secret": r.get("secret", True)} for r in key_rows],
            "new_repo": owner, "no_new_repo": not new_repo.get("on")}
    if field:
        opts["code" if kind == "code" else kind] = source[field]
    return opts


def purge_jobs(jobs: dict) -> None:
    """Forget jobs that finished more than an hour ago."""
    now = time.time()
    for key in [k for k, j in jobs.items() if j["status"] != "running" and now - j["finished_at"] > JOB_KEEP_SECONDS]:
        del jobs[key]


def run_create_job(httpd, job: dict, opts: dict) -> None:
    """Background thread: create the project, turning progress lines into job steps."""
    def progress(line):
        with httpd.jobs_lock:
            if job["steps"]:
                job["steps"][-1]["status"] = "done"
            job["steps"].append({"label": line, "status": "running"})

    try:
        with httpd.write_lock:
            projects.new(opts, WHO, progress=progress)
        status, message = "done", ""
    except common.OpsError as err:
        status, message = "failed", str(err)
    except Exception:
        api_log(traceback.format_exc())
        status, message = "failed", SERVER_ERROR
    with httpd.jobs_lock:
        if job["steps"]:
            job["steps"][-1]["status"] = "done" if status == "done" else "failed"
        job["message"], job["finished_at"], job["status"] = message, time.time(), status


def post_create(req):
    """Start creating a project in the background and reply with the job id."""
    opts = create_opts(req.body)
    httpd = req.server
    with httpd.jobs_lock:
        purge_jobs(httpd.jobs)
        if any(j["status"] == "running" and j["kind"] == "create" for j in httpd.jobs.values()):
            raise common.Conflict(CREATE_BUSY)
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "kind": "create", "project": opts["name"], "status": "running",
               "steps": [], "message": "", "finished_at": 0.0}
        httpd.jobs[job_id] = job
    threading.Thread(target=run_create_job, args=(httpd, job, opts), daemon=True).start()
    return {"job": job_id}


def run_deploy_job(httpd, job: dict, project: str) -> None:
    """Background thread: deploy the project now and keep the result on the job."""
    result, status, message = None, "done", ""
    try:
        result = deploy.now(project, who=WHO, yes=True)
        if not result.get("ok"):
            status, message = "failed", result.get("message", "")
    except common.OpsError as err:
        status, message = "failed", str(err)
    except Exception:
        api_log(traceback.format_exc())
        status, message = "failed", SERVER_ERROR
    with httpd.jobs_lock:
        job["result"], job["message"], job["finished_at"], job["status"] = result, message, time.time(), status


def post_deploy(req, name):
    """Start a deploy in the background (needs yes) and reply with the job id; one deploy job at a time."""
    check_name(name)
    if req.body.get("yes") is not True:
        raise BadRequest("Deploying needs confirmation.")
    common.project_dir(name)
    httpd = req.server
    with httpd.jobs_lock:
        purge_jobs(httpd.jobs)
        if any(j["status"] == "running" and j["kind"] == "deploy" for j in httpd.jobs.values()):
            raise common.Conflict(DEPLOY_BUSY)
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "kind": "deploy", "project": name, "status": "running",
               "steps": [], "message": "", "result": None, "finished_at": 0.0}
        httpd.jobs[job_id] = job
    threading.Thread(target=run_deploy_job, args=(httpd, job, name), daemon=True).start()
    return {"job": job_id}


def post_update_install(req):
    """Queue an install of the given (or newest) tag; the updater runs as its own unit."""
    tag = body_text(req, "tag", False)
    out = update.install(tag, WHO, req.body.get("yes") is True)
    return {"ok": True, "queued": bool(out.get("queued")), "tag": out.get("tag")}


def post_update_rollback(req):
    """Queue a rollback to the previous version."""
    out = update.rollback(WHO, req.body.get("yes") is True)
    return {"ok": True, "queued": bool(out.get("queued"))}


def get_job(req, job_id):
    """Reply with a background job's progress."""
    with req.server.jobs_lock:
        purge_jobs(req.server.jobs)
        job = req.server.jobs.get(job_id)
        if job is None:
            raise common.NotFound("There is no job with that id.")
        return {k: (list(map(dict, v)) if k == "steps" else v) for k, v in job.items() if k != "finished_at"}


def post_edit(req, name):
    """Edit a project's description, repo, profile or services."""
    check_name(name)
    body = req.body
    fields = {}
    for key in ("description", "repo", "profile"):
        if body.get(key) is not None:
            fields[key] = body_text(req, key)
    services = body.get("services")
    if services is not None and (not isinstance(services, list) or not all(isinstance(x, str) for x in services)):
        raise BadRequest("'services' should be a list of names.")
    if ("repo" in fields or "profile" in fields) and body.get("confirm") is not True:
        raise NeedsConfirm()
    with req.server.write_lock:
        if fields or services is None:
            projects.edit(name, WHO, description=fields.get("description"), profile=fields.get("profile"),
                          repo=fields.get("repo"))
        if services is not None:
            projects.set_services(name, services, WHO)
    return get_project(req, name)


def post_remove(req, name):
    """Remove a project from Phoenix (needs confirm); files are kept."""
    if req.body.get("confirm") is not True and req.body.get("yes") is not True:
        raise BadRequest("Removing a project needs \"confirm\": true.")
    with req.server.write_lock:
        return projects.remove(check_name(name), WHO)


def get_import_candidates(req):
    """Reply with what can be imported."""
    return projects.import_candidates()


def get_folders(req):
    """Reply with the sub-folders of a folder under the projects root."""
    return projects.list_folders(req.query.get("path", ""))


def post_import(req):
    """Import a removed project or an unlisted folder."""
    with req.server.write_lock:
        return projects.import_(body_text(req, "target"), WHO)


def post_keys_save(req, name):
    """Save project keys."""
    rows = req.body.get("rows")
    if not isinstance(rows, list):
        raise BadRequest("'rows' should be a list.")
    with req.server.write_lock:
        return keys.save(check_name(name), rows, WHO)


def post_keys_reveal(req, name):
    """Reveal one key value."""
    key = body_text(req, "name")
    with req.server.write_lock:
        return keys.reveal(check_name(name), key, WHO)


def post_keys_remove(req, name):
    """Remove a project key."""
    key = body_text(req, "name")
    with req.server.write_lock:
        keys.remove(check_name(name), key, WHO)
    return keys.rows(name)


def post_settings(req, name):
    """Set project settings."""
    values = body_dict(req, "set")
    with req.server.write_lock:
        settings.set_many(check_name(name), values, WHO)
    return settings.show(name)


def post_preset(req, name):
    """Apply a preset to a project."""
    preset = body_text(req, "preset")
    with req.server.write_lock:
        settings.preset(check_name(name), preset, who=WHO)
    return settings.show(name)


def post_settings_check(req, name):
    """Re-check a project's settings."""
    with req.server.write_lock:
        settings.check(check_name(name))
    return settings.show(name)


def post_plan(req, name):
    """Reply with the build plan for the given overrides."""
    return runs.plan(check_name(name), body_dict(req, "overrides"))


def post_defaults(req, name):
    """Save overrides as the project's defaults."""
    with req.server.write_lock:
        return settings.save_defaults(check_name(name), body_dict(req, "overrides"), WHO)


def post_run_start(req, name):
    """Start a run from the project's notes."""
    spec, brief = body_text(req, "spec", False), body_text(req, "brief", False)
    overrides = body_dict(req, "overrides")
    with req.server.write_lock:
        started = runs.start_from_notes(check_name(name), spec=spec, brief=brief, overrides=overrides, who=WHO)
    return {k: started[k] for k in ("run_id", "project", "status")}


def post_run_stop(req, project, run_id):
    """Stop a run."""
    if req.body.get("confirm") is not True:
        raise BadRequest("Stopping a run needs confirmation.")
    with req.server.write_lock:
        return runs.stop(check_run_id(run_id), who=WHO, project=check_name(project))


def get_gate_review(req, gate_id):
    """Reply with the merge review of a merge gate."""
    if not GATE_ID_RE.match(gate_id):
        raise BadRequest("That isn't a valid gate id.")
    return gates.review(gate_id)


def post_gate_answer(req, gate_id):
    """Answer a gate."""
    if not GATE_ID_RE.match(gate_id):
        raise BadRequest("That isn't a valid gate id.")
    action = body_text(req, "action")
    note = body_text(req, "note", False) or ""
    with req.server.write_lock:
        return gates.answer(gate_id, action, note, who=WHO)


def post_service_connect(req, name):
    """Save a service's account keys; the values are never logged or echoed."""
    values = body_dict(req, "values")
    if not all(isinstance(v, str) for v in values.values()):
        raise BadRequest("'values' should map key names to text.")
    extra = req.body.get("settings") or {}
    if not isinstance(extra, dict):
        raise BadRequest("'settings' should map setting names to text.")
    scrub.add_secrets(v for v in values.values() if v)
    with req.server.write_lock:
        return services.connect(check_name(name), values, who=WHO, settings_in=extra)


def post_service_test(req, name):
    """Try a service's key (the pasted one, else the saved one); nothing is saved."""
    values = req.body.get("values") or {}
    if not isinstance(values, dict) or not all(isinstance(v, str) for v in values.values()):
        raise BadRequest("'values' should map key names to text.")
    scrub.add_secrets(v for v in values.values() if v)
    return services.test(check_name(name), values, who=WHO)


def post_global_models(req):
    """Save Phoenix's default models: {steps: {step: {model, fallback_models}}}."""
    steps = body_dict(req, "steps")
    with req.server.write_lock:
        return app.set_default_models(steps, who=WHO)


def post_service_disconnect(req, name):
    """Remove a service's account keys (needs yes)."""
    with req.server.write_lock:
        return services.disconnect(check_name(name), who=WHO, yes=req.body.get("yes") is True)


NAME = r"(?P<name>[^/]+)"
ROUTES = [  # first match wins, so check-name comes before <name>
    ("GET", r"/api/info", get_info),
    ("GET", r"/api/health", get_health),
    ("GET", r"/api/update", get_update),
    ("GET", r"/api/update/log", get_update_log),
    ("GET", rf"/api/projects/{NAME}/deploys", get_deploys),
    ("GET", r"/api/projects", get_projects),
    ("GET", r"/api/import/candidates", get_import_candidates),
    ("GET", r"/api/folders", get_folders),
    ("GET", r"/api/projects/check-name", get_check_name),
    ("GET", rf"/api/projects/{NAME}", get_project),
    ("GET", rf"/api/projects/{NAME}/changelog", get_changelog),
    ("GET", rf"/api/projects/{NAME}/keys", get_keys),
    ("GET", rf"/api/projects/{NAME}/settings", get_settings),
    ("GET", rf"/api/projects/{NAME}/explain", get_explain),
    ("GET", rf"/api/projects/{NAME}/specs", get_specs),
    ("GET", rf"/api/projects/{NAME}/runs", get_builds),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)", get_run),
    ("GET", r"/api/events/recent", get_events_recent),
    ("GET", r"/api/logs", get_logs),
    ("GET", r"/api/logs/read", get_logs_read),
    ("GET", r"/api/gates", get_gates),
    ("GET", r"/api/gates/(?P<gate_id>[^/]+)/review", get_gate_review),
    ("GET", r"/api/library/steps", get_steps),
    ("GET", r"/api/library/profiles", get_profiles),
    ("GET", r"/api/library/presets", get_presets),
    ("GET", r"/api/library/templates", get_templates),
    ("GET", r"/api/library/services", get_services_lib),
    ("GET", r"/api/library/tools", get_tools_lib),
    ("GET", r"/api/github/repos", get_repos),
    ("GET", r"/api/global", get_global),
    ("GET", r"/api/global/services", get_global_services),
    ("GET", r"/api/doctor", get_doctor),
    ("GET", r"/api/update/history", get_update_history),
    ("GET", r"/api/services", get_services),
    ("GET", r"/api/keys/audit", get_keys_audit),
    ("GET", r"/api/jobs/(?P<job_id>[0-9a-f]+)", get_job),
    ("POST", r"/api/projects", post_create),
    ("POST", r"/api/import", post_import),
    ("POST", rf"/api/projects/{NAME}/remove", post_remove),
    ("POST", r"/api/update/install", post_update_install),
    ("POST", r"/api/update/rollback", post_update_rollback),
    ("POST", rf"/api/projects/{NAME}/deploy", post_deploy),
    ("POST", rf"/api/services/{NAME}/connect", post_service_connect),
    ("POST", rf"/api/services/{NAME}/disconnect", post_service_disconnect),
    ("POST", rf"/api/services/{NAME}/test", post_service_test),
    ("POST", r"/api/global/models", post_global_models),
    ("POST", rf"/api/projects/{NAME}/edit", post_edit),
    ("POST", rf"/api/projects/{NAME}/keys/save", post_keys_save),
    ("POST", rf"/api/projects/{NAME}/keys/reveal", post_keys_reveal),
    ("POST", rf"/api/projects/{NAME}/keys/remove", post_keys_remove),
    ("POST", rf"/api/projects/{NAME}/settings", post_settings),
    ("POST", rf"/api/projects/{NAME}/settings/preset", post_preset),
    ("POST", rf"/api/projects/{NAME}/settings/check", post_settings_check),
    ("POST", rf"/api/projects/{NAME}/plan", post_plan),
    ("POST", rf"/api/projects/{NAME}/defaults", post_defaults),
    ("POST", rf"/api/projects/{NAME}/runs", post_run_start),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/stop", post_run_stop),
    ("POST", r"/api/gates/(?P<gate_id>[^/]+)/answer", post_gate_answer),
]
COMPILED = [(m, re.compile(rf"^{p}/?$"), h) for m, p, h in ROUTES]


def find_route(method: str, path: str):
    """The (handler, path params) of the first matching route, or None."""
    for m, rx, handler in COMPILED:
        found = rx.match(path) if m == method else None
        if found:
            return handler, found.groupdict()
    return None


class Handler(BaseHTTPRequestHandler):
    """One request: guard (POST), body (POST), route, reply, log."""
    server_version = "phoenix-api"

    # ported from reference/selector/selector/server.py:119 (send_json)
    def send_raw(self, status, content_type, raw, cache="no-store"):
        self.status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, status, data):
        self.send_raw(status, "application/json; charset=utf-8", json.dumps(data).encode())

    def fail(self, status, message):
        self.send_json(status, {"ok": False, "message": message})

    def log_message(self, *args):  # the stderr line is replaced by api_log in handle_request
        pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def handle_request(self, method):
        started = time.monotonic()
        url = urlsplit(self.path)
        self.path_only = url.path
        self.query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        self.status = 0
        try:
            self.dispatch(method)
        except (BrokenPipeError, ConnectionResetError):
            self.log_done(method, started)
        except Exception:
            api_log(traceback.format_exc())
            self.status = 500
            self.log_done(method, started)  # logged before the reply so a fast reader sees it
            self.fail(500, SERVER_ERROR)
        else:
            self.log_done(method, started)

    def log_done(self, method, started):
        """Write the one-line request record to api.log."""
        api_log(f"{method} {self.path_only} {self.status} {(time.monotonic() - started) * 1000:.0f}ms")

    def dispatch(self, method):
        if method == "POST":
            if not self.guard_ok():
                return self.fail(403, "Refused: this request didn't come from the Phoenix dashboard.")
            if self.read_body() is None:
                return
        if method == "GET" and self.path_only.rstrip("/") == "/api/events":
            return stream.serve(self)
        route = find_route(method, self.path_only)
        if route is None:
            if method == "GET" and not self.path_only.startswith("/api/"):
                return self.send_static()
            return self.fail(404, "Not found.")
        handler, params = route
        try:
            self.send_json(200, {"ok": True, "data": handler(self, **params)})
        except BadRequest as err:
            self.fail(400, str(err))
        except NeedsConfirm:
            self.send_json(409, {"ok": False, "message": "Changing the repo or profile needs confirmation.",
                                 "needs_confirm": True})
        except common.NotFound as err:
            self.fail(404, str(err))
        except common.Conflict as err:
            self.fail(409, str(err))
        except common.OpsError as err:
            self.fail(400, str(err))

    def guard_ok(self):
        """True when the request carries the Phoenix header and an allowed Origin."""
        return self.headers.get("X-Phoenix") == "1" and self.headers.get("Origin") in allowed_origins()

    # ported from reference/selector/selector/server.py:169 (read_body)
    def read_body(self):
        """The JSON object sent with a POST (kept in self.body), or None after replying 400."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True  # don't read a body we refuse
            self.fail(400, "The request was too big.")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            self.fail(400, "The request wasn't valid JSON.")
            return None
        if not isinstance(body, dict):
            self.fail(400, "The request should be a JSON object.")
            return None
        self.body = body
        return body

    def send_static(self):
        """Serve a file of the built web app, or the 'not built' page, or a JSON 404."""
        dist = Path(self.server.web_dist).resolve()
        rel = unquote(self.path_only).lstrip("/")
        if rel in ("", "index.html"):
            index = dist / "index.html"
            if not index.is_file():
                return self.send_raw(200, "text/html; charset=utf-8", NOT_BUILT)
            return self.send_raw(200, "text/html; charset=utf-8", index.read_bytes())
        try:
            target = (dist / rel).resolve()
            ok = target.is_relative_to(dist) and target.is_file()
        except (ValueError, OSError):
            ok = False
        if not ok:
            return self.fail(404, "Not found.")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-store"
        self.send_raw(200, kind, target.read_bytes(), cache)


# ported from reference/selector/selector/server.py:197 (make_server)
def make_server(port: int, host: str = "127.0.0.1", web_dist=None) -> ThreadingHTTPServer:
    """Build the API server on 127.0.0.1 (not started); `host` may only say localhost."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("The API only listens on 127.0.0.1.")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    httpd.write_lock = threading.Lock()   # one write at a time
    httpd.stopping = threading.Event()
    httpd.jobs_lock = threading.Lock()
    httpd.jobs = {}                       # background jobs by id
    httpd.tag = app.release_tag()             # the running copy's release tag, read once
    httpd.streams_lock = threading.Lock()
    httpd.streams = 0                     # open live event streams
    httpd.web_dist = Path(web_dist) if web_dist else paths.library() / "web" / "dist"
    return httpd
