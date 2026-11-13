"""The dashboard API server: JSON under /api, the built web app as static files, nothing else."""
import base64
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
from phoenix9.ops import agent as ops_agent, bell as ops_bell, agentaccess, agentnext as ops_agentnext, app, blocks as ops_blocks, cards as ops_cards, chat as ops_chat, common, deploy, docs as ops_docs, search as ops_search, doctor as ops_doctor, gates, github, images as ops_images, keys, library, logs, projects, reference as ops_reference, repair as ops_repair, report as ops_report, runs, service as ops_service, timing, services, settings, suggest as ops_suggest, ui as ops_ui, update, work as ops_work

MAX_BODY = 64 * 1024
MAX_UPLOAD_BODY = 8 * 1024 * 1024  # only POST .../reference/files: a 5 MB file in base64 plus its name
MAX_AGENT_BODY = 4 * ops_agent.MAX_CHARS + 4096  # room for a full-size message (the 400 comes from the send itself)
ORIGINS_ENV = "PHOENIX_API_ORIGINS"
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
IMAGES_BUSY = "Images are being built already; try again when that has finished."
RESTART_BUSY = "A restart is already waiting; try again when it has finished."
WHO = "dashboard"
AGENT_NEXT = "/api/agent-next"


class BadRequest(Exception):
    """The request itself is wrong (answered 400 before any ops call)."""


class RawReply:
    """A handler result sent as it is (not wrapped in JSON): content type, body bytes and extra headers."""

    def __init__(self, content_type, body, headers):
        self.content_type, self.body, self.headers = content_type, body, headers


class NeedsConfirm(Exception):
    """A change that needs `"confirm": true` in the body (answered 409 with needs_confirm)."""


def allowed_origins() -> list[str]:
    """The origins allowed to POST: PHOENIX_API_ORIGINS (how api.env hands the setting to this process), else
    the allowed_origins global setting; read on each request."""
    raw = os.environ.get(ORIGINS_ENV, "")
    found = [o.strip() for o in raw.split(",") if o.strip()]
    return found or app.addresses_view()["allowed_origins"]


def migrate_addresses() -> None:
    """At start: the one-time move to the dashboard address settings; this process then uses the new origins."""
    try:
        done = app.migrate_addresses_at_start()
    except Exception:
        api_log(traceback.format_exc())
        return
    if done:
        os.environ[ORIGINS_ENV] = ",".join(done["allowed_origins"])
        api_log(f"dashboard addresses: allowed origins are now {', '.join(done['allowed_origins'])}")


def refusal(headers) -> str:
    """The plain refusal for a write the guard turned away, naming the page origin it saw."""
    origin = headers.get("Origin")
    if headers.get("X-Phoenix") != "1" or not origin:
        return "Refused: this request didn't come from the Phoenix dashboard."
    return (f"Refused: this page was opened from {origin}, which Phoenix doesn't allow yet. Add it in Global "
            "settings > Dashboard addresses (or run `phoenix settings global set allowed_origins=...`).")


NOT_ROOT = ("Refused: this request came from a program on the server that isn't run by root (or another user "
            "Phoenix allows).")
PEER_UNKNOWN = "Refused: Phoenix couldn't tell which program on the server sent this request."
NO_ACCESS = "Refused: Phoenix needs a Cloudflare Access sign-in. Open the dashboard through its Access address."
WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")


OPEN_PATHS = ("/api/health",)   # answered for any local program, with no Access token: the doctor, the updater and
                                # `phoenix service restart` call it; it shows only the version, tag and an origins digest


def peer_uid_of(handler):
    """The uid of the program at the far end of the connection (None when it cannot be told)."""
    try:
        return app.write_peer_uid(handler.client_address, handler.connection.getsockname())
    except Exception:
        api_log(traceback.format_exc())
        return None


def peer_refusal(handler, uid=None) -> str:
    """'' when the far end of the connection is a process run by an allowed uid (access.peer_uids, default root:
    cloudflared and code-server run as root); else the plain refusal. The owner is looked up through the host
    adapter (/proc/net/tcp on the real host)."""
    uid = peer_uid_of(handler) if uid is None else uid
    if uid is None:
        return PEER_UNKNOWN
    try:
        allowed = app.allowed_peer_uids()
    except Exception:
        api_log(traceback.format_exc())
        allowed = [0]
    return "" if uid in allowed else NOT_ROOT


def access_refusal(headers) -> str:
    """'' when the optional Cloudflare Access lock is off or the request carries a valid token; else the refusal."""
    why = app.access_lock_problem(headers.get("Cf-Access-Jwt-Assertion"))
    if why is None:
        return ""
    api_log(f"request refused by the Access lock: {why}")
    return NO_ACCESS


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
    """Reply that the server is up: version, tag and a digest of the allowed origins only (any local program may
    ask, so nothing else; no ops call that can fail)."""
    import phoenix9
    return {"ok": True, "version": phoenix9.__version__, "tag": req.server.tag,
            "origins_digest": app.origins_digest(allowed_origins())}


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
    """Reply with one project's details (409 for the Phoenix agent's own folder, which is not a project)."""
    if name == projects.agent_name():
        raise common.Conflict(projects.AGENT_FOLDER_TEXT)
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


def get_reference(req, name):
    """Reply with a project's reference files and links."""
    return ops_reference.show(check_name(name))


def post_reference_file(req, name):
    """Upload one reference file ({filename, data_base64, replace?})."""
    filename = body_text(req, "filename")
    encoded = body_text(req, "data_base64")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise BadRequest("'data_base64' should be the file's bytes in base64.") from None
    with req.server.write_lock:
        return ops_reference.add(check_name(name), filename, data, req.who, replace=req.body.get("replace") is True)


def put_reference_vision(req, name):
    """Save the owner's vision text ({text}) as vision.md."""
    text = body_text(req, "text")
    with req.server.write_lock:
        return ops_reference.set_vision(check_name(name), text, req.who)


def delete_reference_file(req, name, filename):
    """Remove one reference file."""
    with req.server.write_lock:
        return ops_reference.remove(check_name(name), unquote(filename), req.who)


def post_reference_file_remove(req, name):
    """Remove one reference file named in the body (for callers that only send GET and POST)."""
    with req.server.write_lock:
        return ops_reference.remove(check_name(name), body_text(req, "filename"), req.who)


def post_reference_links(req, name):
    """Add the links in some text ({text})."""
    text = body_text(req, "text")
    with req.server.write_lock:
        return ops_reference.add_links(check_name(name), text, req.who)


def delete_reference_link(req, name):
    """Remove one reference link ({url})."""
    with req.server.write_lock:
        return ops_reference.remove_link(check_name(name), body_text(req, "url"), req.who)


post_reference_link_remove = delete_reference_link  # the same remove, for callers that only send GET and POST


def get_builds(req, name):
    """Reply with a project's builds."""
    return runs.builds(check_name(name), int_param(req, "limit", 10))


def get_run(req, project, run_id):
    """Reply with one run's detail."""
    return runs.detail(check_name(project), check_run_id(run_id))


def get_bell(req):
    """Reply with {count, items}: what needs Alex right now."""
    return ops_bell.show()


def post_bell_dismiss(req):
    """Dismiss one bell item ({id} in the body) and reply with the new {count, items}."""
    item_id = body_text(req, "id")
    with req.server.write_lock:
        try:
            return ops_bell.dismiss(item_id, WHO)
        except common.OpsError as e:
            raise BadRequest(str(e)) from None


def post_bell_dismiss_all(req):
    """Dismiss every bell item shown now and reply with the new {count, items}."""
    with req.server.write_lock:
        return ops_bell.dismiss_all(WHO)


def get_report_daily(req):
    """Reply with the newest saved daily report ({date, text})."""
    return ops_report.daily_latest()


def get_report_daily_now(req):
    """Reply with a daily report built right now (nothing is sent or saved)."""
    return ops_report.daily_now()


def get_search(req):
    """Reply with search results for ?q= (optional ?kind= and ?limit=); a bad query is a 400."""
    return ops_search.run(req.query.get("q", ""), req.query.get("kind") or None, int_param(req, "limit", 20))


def get_run_events(req, project, run_id):
    """Reply with one run's events, oldest first."""
    after = req.query.get("after")
    return runs.events(check_name(project), check_run_id(run_id), int_param(req, "after", 0) if after else None,
                       min(max(int_param(req, "limit", 50), 1), 1000))


def get_run_tries(req, project, run_id):
    """Reply with one task's tries (the first failed, waiting or stuck task unless `task` is given)."""
    task = req.query.get("task")
    return runs.task_tries(check_name(project), check_run_id(run_id), int_param(req, "task", 0) if task else None)


def get_run_timing(req, project, run_id):
    """Reply with where one run's time went."""
    return timing.timing(check_name(project), check_run_id(run_id))


def get_run_session(req, project, run_id):
    """Reply with the scrubbed last lines of one step's AI session."""
    task = req.query.get("task")
    if task is None:
        raise BadRequest("Give the task number (?task=N).")
    attempt = req.query.get("attempt")
    return runs.session_excerpt(check_name(project), check_run_id(run_id), int_param(req, "task", 0),
                                int_param(req, "attempt", 0) if attempt else None, req.query.get("step") or None)


def get_gates(req):
    """Reply with the open and answered gates."""
    name = req.query.get("project")
    return gates.list_(check_name(name) if name else None)


def get_cards(req):
    """Reply with a ready card built from live data (bad JSON or a bad query is a 400 with the reason)."""
    try:
        query = json.loads(req.query.get("query") or "{}")
    except ValueError:
        raise BadRequest("'query' should be a JSON object.")
    return ops_cards.build(req.query.get("type", ""), query, req.query.get("title") or None)


def get_docs_list(req):
    """Reply with a run's documents."""
    return ops_docs.list(check_run_id(req.query.get("run", "")))


def get_docs_show(req):
    """Reply with one document's scrubbed text."""
    return ops_docs.show(req.query.get("id", ""))


def get_docs_download(req):
    """Reply with one document as a scrubbed attachment."""
    doc = ops_docs.download(req.query.get("id", ""))
    return RawReply("text/plain; charset=utf-8", doc["text"].encode(),
                    {"Content-Disposition": f'attachment; filename="{doc["name"]}"',
                     "X-Content-Type-Options": "nosniff"})


def post_ui_go(req):
    """Move the open dashboard to a page (400 with the reason when the page or its options are wrong)."""
    return ops_ui.go(body_text(req, "to"), body_dict(req, "params"), WHO)


def post_blocks_check(req):
    """Check one reply block ({kind, json}); the answer is {ok, reason, resolved}."""
    return ops_blocks.check({"kind": body_text(req, "kind"), "json": body_text(req, "json")})


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


def get_routes(req):
    """Reply with the dashboard pages the agent may point at (routes.ROUTES)."""
    return agentaccess.pages()


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


def get_agent(req):
    """Reply with the Phoenix agent's state."""
    return ops_agent.status()


def get_agent_messages(req):
    """Reply with panel items after a line number."""
    after, limit = int_param(req, "after", 0), int_param(req, "limit", 100)
    if after < 0 or limit < 0:
        raise BadRequest("'after' and 'limit' should not be negative.")
    return ops_agent.messages(after, min(limit, 1000), req.query.get("session") or None)


def get_agent_sessions(req):
    """Reply with the agent's earlier conversations."""
    return ops_agent.sessions()


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


def run_create_job(httpd, job: dict, opts: dict, who: str = WHO) -> None:
    """Background thread: create the project, turning progress lines into job steps."""
    def progress(line):
        with httpd.jobs_lock:
            if job["steps"]:
                job["steps"][-1]["status"] = "done"
            job["steps"].append({"label": line, "status": "running"})

    try:
        with httpd.write_lock:
            projects.new(opts, who, progress=progress)
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
    threading.Thread(target=run_create_job, args=(httpd, job, opts, req.who), daemon=True).start()
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


def run_images_job(httpd, job: dict, profiles: list, build_all: bool, changed: bool) -> None:
    """Background thread: build the step images, one job step per progress line, and keep the result."""
    def progress(line):
        with httpd.jobs_lock:
            job["steps"].append({"label": line, "status": "done"})

    result, status, message = None, "done", ""
    try:
        result = ops_images.build(profiles, build_all, changed, say=progress)
        if not result["ok"]:
            status, message = "failed", "At least one image failed to build; see the image logs."
    except common.OpsError as err:
        status, message = "failed", str(err)
    except Exception:
        api_log(traceback.format_exc())
        status, message = "failed", SERVER_ERROR
    with httpd.jobs_lock:
        job["result"], job["message"], job["finished_at"], job["status"] = result, message, time.time(), status


def post_images_build(req):
    """Start building step images in the background: {profiles: [...]} and/or {all, changed}; one build at a time."""
    profiles = req.body.get("profiles") or []
    build_all, changed = req.body.get("all", False), req.body.get("changed", False)
    if not isinstance(profiles, list) or not all(isinstance(p, str) and p for p in profiles):
        raise BadRequest("'profiles' should be a list of profile names.")
    if not isinstance(build_all, bool) or not isinstance(changed, bool):
        raise BadRequest("'all' and 'changed' should be true or false.")
    ops_images.choose(profiles, build_all)          # an unknown profile is refused now, not in the job
    httpd = req.server
    with httpd.jobs_lock:
        purge_jobs(httpd.jobs)
        if any(j["status"] == "running" and j["kind"] == "images" for j in httpd.jobs.values()):
            raise common.Conflict(IMAGES_BUSY)
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "kind": "images", "project": None, "status": "running",
               "steps": [], "message": "", "result": None, "finished_at": 0.0}
        httpd.jobs[job_id] = job
    common.record_command(WHO, "images build" + (" --all" if build_all else "") + (" --changed" if changed else "")
                          + "".join(f" --profile {p}" for p in profiles))
    threading.Thread(target=run_images_job, args=(httpd, job, profiles, build_all, changed), daemon=True).start()
    return {"job": job_id}


def run_restart_job(httpd, job: dict, name: str) -> None:
    """Background thread: restart the runner (it may wait up to 30 minutes for a task boundary)."""
    def progress(line):
        with httpd.jobs_lock:
            job["steps"].append({"label": line, "status": "done"})

    result, status, message = None, "done", ""
    try:
        result = ops_service.restart(name, who=WHO, yes=True, say=progress)
    except common.OpsError as err:
        status, message = "failed", str(err)
    except Exception:
        api_log(traceback.format_exc())
        status, message = "failed", SERVER_ERROR
    with httpd.jobs_lock:
        job["result"], job["message"], job["finished_at"], job["status"] = result, message, time.time(), status


def post_service_restart(req, name):
    """Restart phoenix-api (at once, without waiting: this process is the one restarted) or phoenix-runner
    (in a background job that waits for a task boundary); needs yes."""
    if name not in ops_service.UNITS:
        raise BadRequest("Say api or runner.")
    if req.body.get("yes") is not True:
        raise BadRequest(f"Restarting {ops_service.UNITS[name]} needs confirmation.")
    if name == "api":
        return ops_service.restart_api_soon(WHO)
    httpd = req.server
    with httpd.jobs_lock:
        purge_jobs(httpd.jobs)
        if any(j["status"] == "running" and j["kind"] == "restart" for j in httpd.jobs.values()):
            raise common.Conflict(RESTART_BUSY)
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "kind": "restart", "project": None, "status": "running",
               "steps": [], "message": "", "result": None, "finished_at": 0.0}
        httpd.jobs[job_id] = job
    threading.Thread(target=run_restart_job, args=(httpd, job, name), daemon=True).start()
    return {"job": job_id}


def post_update_install(req):
    """Queue an install of the given (or newest) tag; the updater runs as its own unit."""
    tag = body_text(req, "tag", False)
    out = update.install(tag, req.who, req.body.get("yes") is True)
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
            projects.edit(name, req.who, description=fields.get("description"), profile=fields.get("profile"),
                          repo=fields.get("repo"))
        if services is not None:
            projects.set_services(name, services, req.who)
    return get_project(req, name)


def post_remove(req, name):
    """Remove a project from Phoenix (needs confirm); files are kept."""
    if req.body.get("confirm") is not True and req.body.get("yes") is not True:
        raise BadRequest("Removing a project needs \"confirm\": true.")
    with req.server.write_lock:
        return projects.remove(check_name(name), WHO)


def get_delete_plan(req, name):
    """Reply with the dry run for deleting a project entirely (nothing is touched)."""
    return projects.delete_plan(check_name(name), WHO)


def post_delete(req, name):
    """Delete a project entirely; the body must hold {"confirm": "<name>"} (the dry run is the GET delete-plan)."""
    check_name(name)
    confirm = req.body.get("confirm")
    if not isinstance(confirm, str) or confirm != name:
        raise BadRequest("Type the project's name to confirm. Nothing was deleted.")
    with req.server.write_lock:
        return projects.delete(name, confirm, WHO)


def post_delete_repo(req, name):
    """Retry deleting the GitHub repo of an already deleted project."""
    with req.server.write_lock:
        return projects.delete_repo(check_name(name), WHO)


def get_chat(req, name):
    """Reply with the project's chat state."""
    return ops_chat.chat_state(check_name(name))


def post_chat_open(req, name):
    """Open the project's chat (starting it if needed)."""
    with req.server.write_lock:
        return ops_chat.open_chat(check_name(name), WHO)


def post_chat_sleep(req, name):
    """Put the project's chat to sleep."""
    with req.server.write_lock:
        return ops_chat.sleep_chat(check_name(name), WHO)


def post_chat_forget(req, name):
    """Stop the project's chat and forget its saved conversation (needs confirm)."""
    check_name(name)
    if req.body.get("confirm") is not True:
        raise BadRequest("Forgetting the saved chat needs \"confirm\": true.")
    with req.server.write_lock:
        return ops_chat.forget_chat(name, WHO)


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
        settings.set_many(check_name(name), values, req.who)
    return settings.show(name)


def post_preset(req, name):
    """Apply a preset to a project."""
    preset = body_text(req, "preset")
    with req.server.write_lock:
        settings.preset(check_name(name), preset, who=req.who)
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
        started = runs.start_from_notes(check_name(name), spec=spec, brief=brief, overrides=overrides, who=req.who)
    return {k: started[k] for k in ("run_id", "project", "status")}


def post_hotfix(req, name):
    """Start a short hotfix build from a brief."""
    brief = body_text(req, "brief", True)
    with req.server.write_lock:
        started = runs.start_hotfix(check_name(name), brief, who=req.who)
    return {k: started[k] for k in ("run_id", "project", "status")}


def post_run_stop(req, project, run_id):
    """Stop a run."""
    if req.body.get("confirm") is not True:
        raise BadRequest("Stopping a run needs confirmation.")
    with req.server.write_lock:
        return runs.stop(check_run_id(run_id), who=req.who, project=check_name(project))


def post_edit_abandon(req, edit_id):
    """Abandon a quick edit (the body must hold {"confirm": true})."""
    if req.body.get("confirm") is not True:
        raise BadRequest("Abandoning a quick edit needs confirmation.")
    with req.server.write_lock:
        return ops_work.abandon_edit(edit_id, WHO)


def post_plan_abandon(req, plan_id):
    """Abandon a planning session (the body must hold {"confirm": true})."""
    if req.body.get("confirm") is not True:
        raise BadRequest("Abandoning a planning session needs confirmation.")
    with req.server.write_lock:
        return ops_work.abandon_plan(plan_id, WHO)


def post_run_pause(req, run_id):
    """Pause now: stop the running step's container and pause the run."""
    if req.body.get("now") is not True:
        raise BadRequest("Pausing needs {\"now\": true}.")
    with req.server.write_lock:
        return runs.pause(check_run_id(run_id), now=True, who=req.who)


def post_run_resume(req, run_id):
    """Resume a paused run."""
    with req.server.write_lock:
        return runs.resume(check_run_id(run_id), who=req.who)


def get_repair_report(req, run_id):
    """Write the run report and reply with it: the markdown and the findings as JSON."""
    run_id = check_run_id(run_id)
    with req.server.write_lock:
        done = ops_repair.report(run_id)
        found = ops_repair.check(run_id)["problems"]
    return {"run_id": done["run_id"], "project": done["project"], "markdown": done["text"], "findings": found}


def get_repair_diagnose(req, run_id):
    """Reply with the typed diagnosis of a stopped or failed run (the project comes in the query)."""
    project = req.query.get("project")
    if not project:
        raise BadRequest("Say which project the run belongs to (project=).")
    return ops_repair.diagnose(check_name(project), check_run_id(run_id))


def get_report_status(req):
    """Reply with the status report the runner rewrites every 10 minutes (markdown); never writes a file
    (when there is no saved copy yet it is built once, outside the write lock, and not saved)."""
    done = ops_report.saved()
    return {"path": done["path"], "markdown": done["text"], "saved": done["saved"]}


def get_suggest(req):
    """Reply with up to three suggestions for the Agent panel strip (empty when the setting is off), read from
    the runner's saved report; never writes a file."""
    return ops_suggest.list_(strip=True, fresh=False)


def post_suggest(req, key, what):
    """Mark a suggestion shown, snoozed (optional {hours}) or dismissed."""
    try:  # the route keeps %3A / %2B as sent; decoded once here, then it must be a plain key
        key = ops_suggest.check_key(unquote(key))
    except common.OpsError as e:
        raise BadRequest(str(e)) from None
    hours = req.body.get("hours", ops_suggest.SNOOZE_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= 24 * 365:
        raise BadRequest("hours has to be a number above 0.")
    with req.server.write_lock:
        try:
            return ops_suggest.mark(key, what, WHO, float(hours))
        except common.OpsError as e:
            raise BadRequest(str(e)) from None


def post_suggest_snooze(req, key):
    """Hide a suggestion for a while."""
    return post_suggest(req, key, "snoozed")


def post_suggest_dismiss(req, key):
    """Never suggest this again."""
    return post_suggest(req, key, "dismissed")


def post_suggest_shown(req, key):
    """Say the suggestion was mentioned to Alex."""
    return post_suggest(req, key, "shown")


def post_repair_apply(req, run_id):
    """Save the posted repair note and apply it (or only show a dry run)."""
    run_id = check_run_id(run_id)
    text = body_text(req, "note")
    flags = {k: req.body.get(k, False) for k in ("dry_run", "approve_unlock")}
    if not all(isinstance(v, bool) for v in flags.values()):
        raise BadRequest("dry_run and approve_unlock have to be true or false.")
    if not flags["dry_run"] and req.body.get("confirm") is not True:
        raise BadRequest("Applying a repair needs confirmation.")
    with req.server.write_lock:
        return ops_repair.apply_text(run_id, text, who=WHO, **flags)


def int_field(req, key: str) -> int | None:
    """A whole number from the body (None when left out), or BadRequest."""
    value = req.body.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise BadRequest(f"'{key}' should be a whole number.")
    return value


def text_field(req, key: str) -> str | None:
    """A string from the body (None when left out), or BadRequest."""
    value = req.body.get(key)
    if value is not None and not isinstance(value, str):
        raise BadRequest(f"'{key}' should be text.")
    return value


def need(value, key: str):
    """The value, or BadRequest saying the field is missing."""
    if value is None:
        raise BadRequest(f"'{key}' is needed.")
    return value


def post_repair_rerun(req, project, run_id):
    """Re-run a task or a finish step of a run through a repair note."""
    run_id, task, step = check_run_id(run_id), int_field(req, "task"), text_field(req, "finish_step")
    with req.server.write_lock:
        return ops_repair.rerun_step(run_id, task, step, who=req.who)


def post_repair_resume(req, project, run_id):
    """Resume a run from a task through a repair note."""
    run_id, task = check_run_id(run_id), need(int_field(req, "task"), "task")
    with req.server.write_lock:
        return ops_repair.resume_from(run_id, task, who=req.who)


def post_repair_skip(req, project, run_id):
    """Skip a task of a run, with a reason, through a repair note."""
    run_id, task = check_run_id(run_id), need(int_field(req, "task"), "task")
    why = need(text_field(req, "why"), "why")
    with req.server.write_lock:
        return ops_repair.skip_task(run_id, task, why, who=req.who)


def post_repair_rewrite_checks(req, project, run_id):
    """Rewrite a task's checks, with a reason, through a repair note."""
    run_id, task = check_run_id(run_id), need(int_field(req, "task"), "task")
    why = need(text_field(req, "why"), "why")
    with req.server.write_lock:
        return ops_repair.rewrite_checks(run_id, task, why, who=req.who)


def post_repair_max_tries(req, project, run_id):
    """Raise a run's max tries through a repair note."""
    run_id, tries = check_run_id(run_id), need(int_field(req, "tries"), "tries")
    with req.server.write_lock:
        return ops_repair.raise_max_tries(run_id, tries, who=req.who)


def post_repair_restart(req, project, run_id):
    """Restart a stopped or failed build on another preset."""
    run_id, preset = check_run_id(run_id), need(text_field(req, "preset"), "preset")
    with req.server.write_lock:
        return ops_repair.restart_on_preset(check_name(project), run_id, preset, who=req.who)


def post_run_note(req, run_id):
    """Add a note to a task of a run (the next attempt reads it)."""
    task = req.body.get("task")
    if isinstance(task, bool) or not isinstance(task, int):
        raise BadRequest("'task' should be a task number.")
    with req.server.write_lock:
        return runs.note(check_run_id(run_id), task, body_text(req, "text"), who=WHO)


def post_run_discard(req, project, run_id):
    """Discard a failed or stopped run's worktree and branch."""
    if req.body.get("confirm") is not True:
        raise BadRequest("Discarding a run's work needs confirmation.")
    force = req.body.get("force", False)
    if not isinstance(force, bool):
        raise BadRequest("force has to be true or false.")
    with req.server.write_lock:
        return runs.discard(check_run_id(run_id), who=WHO, project=check_name(project), force=force)


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
        return gates.answer(gate_id, action, note, who=req.who, by=req.body.get("by"))


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


def post_global_addresses(req):
    """Save the dashboard addresses ({dashboard_url?, allowed_origins?, vscode_url?}); a change of the allowed
    origins rewrites api.env and asks systemd to restart this API."""
    changes = {k: req.body[k] for k in app.ADDRESS_KEYS if k in req.body}
    unknown = sorted(set(req.body) - set(app.ADDRESS_KEYS))
    if unknown:
        raise BadRequest(f"'{unknown[0]}' is not a dashboard address setting.")
    with req.server.write_lock:
        return app.set_addresses(changes, who=req.who, own_origin=req.headers.get("Origin"))


def post_global_models(req):
    """Save Phoenix's default models: {steps: {step: {model, fallback_models}}}."""
    steps = body_dict(req, "steps")
    with req.server.write_lock:
        return app.set_default_models(steps, who=req.who)


def post_agent_send(req):
    """Send a message to the Phoenix agent (503 when it is asleep, 400 when too long)."""
    return ops_agent.send(body_text(req, "text"), body_dict(req, "context"), WHO, panel=True)


def post_agent_restart(req):
    """Restart the Phoenix agent's service (the body must be {"confirm": true}, else 409)."""
    if req.body.get("confirm") is not True:
        raise common.Conflict("Restarting the Phoenix agent needs \"confirm\": true. Nothing was restarted.")
    with req.server.write_lock:
        return ops_agent.restart(WHO)


def post_agent_stop(req):
    """Stop the Phoenix agent's running command and tell it to stop (503 when it is asleep); no write lock."""
    return ops_agent.stop(WHO)


def post_agent_new(req):
    """Start a fresh agent conversation (body {"confirm": true}, else 409); waits without the write lock."""
    if req.body.get("confirm") is not True:
        raise common.Conflict("A new conversation needs \"confirm\": true. Nothing was changed.")
    return ops_agent.new_conversation(WHO)


def post_service_disconnect(req, name):
    """Remove a service's account keys (needs yes)."""
    with req.server.write_lock:
        return services.disconnect(check_name(name), who=WHO, yes=req.body.get("yes") is True)


NAME = r"(?P<name>[^/]+)"
ROUTES = [  # first match wins, so check-name comes before <name>
    ("GET", r"/api/info", get_info),
    ("GET", r"/api/routes", get_routes),
    ("GET", r"/api/health", get_health),
    ("GET", r"/api/update", get_update),
    ("GET", r"/api/update/log", get_update_log),
    ("GET", rf"/api/projects/{NAME}/deploys", get_deploys),
    ("GET", rf"/api/chat/{NAME}", get_chat),
    ("GET", r"/api/projects", get_projects),
    ("GET", r"/api/import/candidates", get_import_candidates),
    ("GET", r"/api/folders", get_folders),
    ("GET", r"/api/projects/check-name", get_check_name),
    ("GET", rf"/api/projects/{NAME}", get_project),
    ("GET", rf"/api/projects/{NAME}/changelog", get_changelog),
    ("GET", rf"/api/projects/{NAME}/delete-plan", get_delete_plan),
    ("GET", rf"/api/projects/{NAME}/keys", get_keys),
    ("GET", rf"/api/projects/{NAME}/settings", get_settings),
    ("GET", rf"/api/projects/{NAME}/explain", get_explain),
    ("GET", rf"/api/projects/{NAME}/specs", get_specs),
    ("GET", rf"/api/projects/{NAME}/reference", get_reference),
    ("POST", rf"/api/projects/{NAME}/reference/files", post_reference_file),
    ("PUT", rf"/api/projects/{NAME}/reference/vision", put_reference_vision),
    ("POST", rf"/api/projects/{NAME}/reference/files/remove", post_reference_file_remove),
    ("DELETE", rf"/api/projects/{NAME}/reference/files/(?P<filename>[^/]+)", delete_reference_file),
    ("POST", rf"/api/projects/{NAME}/reference/links", post_reference_links),
    ("POST", rf"/api/projects/{NAME}/reference/links/remove", post_reference_link_remove),
    ("DELETE", rf"/api/projects/{NAME}/reference/links", delete_reference_link),
    ("GET", rf"/api/projects/{NAME}/runs", get_builds),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/events", get_run_events),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/tries", get_run_tries),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/timing", get_run_timing),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/session", get_run_session),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)", get_run),
    ("GET", r"/api/events/recent", get_events_recent),
    ("GET", r"/api/cards", get_cards),
    ("GET", r"/api/bell", get_bell),
    ("POST", r"/api/bell/dismiss", post_bell_dismiss),
    ("POST", r"/api/bell/dismiss-all", post_bell_dismiss_all),
    ("GET", r"/api/search", get_search),
    ("GET", r"/api/docs/list", get_docs_list),
    ("GET", r"/api/docs/show", get_docs_show),
    ("GET", r"/api/docs/download", get_docs_download),
    ("GET", r"/api/agent", get_agent),
    ("GET", r"/api/agent/messages", get_agent_messages),
    ("GET", r"/api/agent/sessions", get_agent_sessions),
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
    ("POST", r"/api/agent/send", post_agent_send),
    ("POST", r"/api/agent/restart", post_agent_restart),
    ("POST", r"/api/agent/stop", post_agent_stop),
    ("POST", r"/api/agent/new", post_agent_new),
    ("POST", r"/api/ui/go", post_ui_go),
    ("POST", r"/api/blocks/check", post_blocks_check),
    ("POST", rf"/api/chat/{NAME}/open", post_chat_open),
    ("POST", rf"/api/chat/{NAME}/sleep", post_chat_sleep),
    ("POST", rf"/api/chat/{NAME}/forget", post_chat_forget),
    ("POST", r"/api/projects", post_create),
    ("POST", r"/api/import", post_import),
    ("POST", rf"/api/projects/{NAME}/remove", post_remove),
    ("POST", rf"/api/projects/{NAME}/delete", post_delete),
    ("POST", rf"/api/projects/{NAME}/delete-repo", post_delete_repo),
    ("POST", r"/api/update/install", post_update_install),
    ("POST", r"/api/update/rollback", post_update_rollback),
    ("POST", rf"/api/projects/{NAME}/deploy", post_deploy),
    ("POST", r"/api/images/build", post_images_build),
    ("POST", rf"/api/service/{NAME}/restart", post_service_restart),
    ("POST", rf"/api/services/{NAME}/connect", post_service_connect),
    ("POST", rf"/api/services/{NAME}/disconnect", post_service_disconnect),
    ("POST", rf"/api/services/{NAME}/test", post_service_test),
    ("POST", r"/api/global/models", post_global_models),
    ("POST", r"/api/global/addresses", post_global_addresses),
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
    ("POST", rf"/api/projects/{NAME}/hotfix", post_hotfix),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/stop", post_run_stop),
    ("POST", r"/api/edits/(?P<edit_id>[^/]+)/abandon", post_edit_abandon),
    ("POST", r"/api/plans/(?P<plan_id>[^/]+)/abandon", post_plan_abandon),
    ("POST", r"/api/runs/(?P<run_id>[^/]+)/pause", post_run_pause),
    ("POST", r"/api/runs/(?P<run_id>[^/]+)/resume", post_run_resume),
    ("POST", r"/api/runs/(?P<run_id>[^/]+)/note", post_run_note),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/discard", post_run_discard),
    ("GET", r"/api/report/status", get_report_status),
    ("GET", r"/api/report/daily", get_report_daily),
    ("GET", r"/api/report/daily/now", get_report_daily_now),
    ("GET", r"/api/suggest", get_suggest),
    ("POST", r"/api/suggest/(?P<key>[A-Za-z0-9._:+%-]+)/snooze", post_suggest_snooze),
    ("POST", r"/api/suggest/(?P<key>[A-Za-z0-9._:+%-]+)/dismiss", post_suggest_dismiss),
    ("POST", r"/api/suggest/(?P<key>[A-Za-z0-9._:+%-]+)/shown", post_suggest_shown),
    ("GET", r"/api/repair/(?P<run_id>[^/]+)/diagnose", get_repair_diagnose),
    ("GET", r"/api/repair/(?P<run_id>[^/]+)/report", get_repair_report),
    ("POST", r"/api/repair/(?P<run_id>[^/]+)/apply", post_repair_apply),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/rerun", post_repair_rerun),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/resume", post_repair_resume),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/skip", post_repair_skip),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/rewrite-checks", post_repair_rewrite_checks),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/max-tries", post_repair_max_tries),
    ("POST", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)/repair/restart", post_repair_restart),
    ("POST", r"/api/gates/(?P<gate_id>[^/]+)/answer", post_gate_answer),
]
UPLOAD_PATH = re.compile(r"^/api/projects/[^/]+/reference/files/?$")
COMPILED = [(m, re.compile(rf"^{p}/?$"), h) for m, p, h in ROUTES]


def find_route(method: str, path: str):
    """The (handler, path params) of the first matching route, or None."""
    for m, rx, handler in COMPILED:
        found = rx.match(path) if m == method else None
        if found:
            return handler, found.groupdict()
    return None


class Handler(BaseHTTPRequestHandler):
    """One request: guard (every route but GET /api/health: allowed peer uid, optional Access token; writes also
    the header and origin), body, route, reply, log."""
    server_version = "phoenix-api"

    # ported from reference/selector/selector/server.py:119 (send_json)
    def send_raw(self, status, content_type, raw, cache="no-store", headers=None):
        self.status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, status, data):
        raw = json.dumps(data)
        if getattr(self, "is_agent", False):
            raw = scrub.scrub(raw)   # every JSON reply to the agent is scrubbed
        self.send_raw(status, "application/json; charset=utf-8", raw.encode())

    def agent_refusal(self, method) -> str:
        """'' when the agent's request has the Phoenix header and is on its route list; else the plain refusal."""
        if self.headers.get("X-Phoenix") != "1":
            return agentaccess.NEEDS_HEADER
        if not agentaccess.route_allowed(method, self.path_only):
            return agentaccess.NOT_ALLOWED
        return ""

    def fail(self, status, message):
        self.send_json(status, {"ok": False, "message": message})

    def log_message(self, *args):  # the stderr line is replaced by api_log in handle_request
        pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def do_PATCH(self):
        self.handle_request("PATCH")

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

    def agent_caller(self) -> bool:
        """True when the far end is the agent's user ([agent_next] uid): it gets only the agentaccess routes."""
        try:
            return agentaccess.is_agent(peer_uid_of(self))
        except Exception:
            api_log(traceback.format_exc())
            return False

    def dispatch(self, method):
        self.who = WHO
        self.is_agent = self.agent_caller()
        if self.is_agent:
            self.who = agentaccess.WHO
            why = self.agent_refusal(method)
            if why:
                self.close_connection = True  # don't read a body we refuse
                return self.fail(403, why)
        elif not (method == "GET" and self.path_only.rstrip("/") in OPEN_PATHS):
            why = peer_refusal(self) or access_refusal(self.headers)
            if why:
                self.close_connection = True  # don't read a body we refuse
                return self.fail(403, why)
        if method in WRITE_METHODS:
            if not self.is_agent and not self.guard_ok():
                self.close_connection = True
                return self.fail(403, refusal(self.headers))
            if self.read_body() is None:
                return
            if self.is_agent:
                why = agentaccess.settings_refusal(method, self.path_only, self.body)
                if why:
                    return self.fail(403, why)
        if method == "GET" and self.path_only.rstrip("/") == "/api/events":
            return stream.serve(self)
        if method == "GET" and self.path_only.rstrip("/") == "/api/agent/stream":
            return stream.serve(self, stream.agent_stream)
        if self.path_only == AGENT_NEXT or self.path_only.startswith(AGENT_NEXT + "/"):
            return self.pass_to_agent(method)
        route = find_route(method, self.path_only)
        if route is None:
            if method == "GET" and not self.path_only.startswith("/api/"):
                return self.send_static()
            return self.fail(404, "Not found.")
        handler, params = route
        try:
            result = handler(self, **params)
            if isinstance(result, RawReply):
                self.send_raw(200, result.content_type, result.body, headers=result.headers)
            else:
                self.send_json(200, {"ok": True, "data": result})
        except BadRequest as err:
            self.fail(400, str(err))
        except NeedsConfirm:
            self.send_json(409, {"ok": False, "message": "Changing the repo or profile needs confirmation.",
                                 "needs_confirm": True})
        except common.NotFound as err:
            self.fail(404, str(err))
        except runs.WouldLoseWork as err:
            self.send_json(409, {"ok": False, "message": str(err), "needs_force": True, "would_lose": err.lost})
        except common.Conflict as err:
            self.fail(409, str(err))
        except common.Unavailable as err:
            self.fail(503, str(err))
        except common.OpsError as err:
            self.fail(400, str(err))

    def pass_to_agent(self, method):
        """Hand /api/agent-next/<path> to the agent service (its reply is passed on as it arrives)."""
        rest = self.path_only[len(AGENT_NEXT):]
        if method not in ("GET", "POST") or not rest.startswith("/") or ".." in rest.split("/") or "//" in rest:
            return self.fail(404, "Not found.")
        query = urlsplit(self.path).query
        headers = {"Accept": self.headers.get("Accept") or "*/*"}
        if self.headers.get("Last-Event-ID"):
            headers["Last-Event-ID"] = self.headers["Last-Event-ID"]
        data = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps(self.body).encode()
        try:
            reply = ops_agentnext.call(method, rest + ("?" + query if query else ""), data, headers)
        except common.Unavailable as err:
            return self.fail(503, str(err))
        if reply.content_type.startswith("text/event-stream"):
            return self.relay_stream(reply)
        raw = b"".join(reply.chunks)
        if method == "GET" and rest == "/status":
            raw = ops_agentnext.tell_no_key(raw)
        self.send_raw(reply.status, reply.content_type, raw)

    def relay_stream(self, reply):
        """Send the agent's event stream on, chunk by chunk, until either side leaves."""
        self.status = reply.status
        self.send_response(reply.status)
        for key, value in (("Content-Type", "text/event-stream"), ("Cache-Control", "no-store"),
                           ("X-Accel-Buffering", "no"), ("Connection", "close")):
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        try:
            for chunk in reply.chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            close = getattr(reply.chunks, "close", None)
            if close:
                close()

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
        limit = MAX_AGENT_BODY if self.path_only.rstrip("/") == "/api/agent/send" else MAX_BODY
        if self.command == "POST" and UPLOAD_PATH.match(self.path_only):
            limit = MAX_UPLOAD_BODY
        if length == 0 and self.command == "DELETE":
            self.body = {}
            return self.body
        if length < 0 or length > limit:
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
    keys.load_secrets()                   # transcript excerpts and logs never show a saved secret
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
