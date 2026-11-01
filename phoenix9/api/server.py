"""The dashboard API server: JSON under /api, the built web app as static files, nothing else."""
import json
import mimetypes
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from phoenix9 import paths, scrub
from phoenix9.ops import app, common, gates, github, keys, library, projects, runs, settings

MAX_BODY = 64 * 1024
DEFAULT_ORIGINS = "https://files.rebirthwebdesign.com.au"
SERVER_ERROR = "Something went wrong; details are in the API log."
NOT_BUILT = (b"<!doctype html><html><head><meta charset=utf-8><title>Phoenix 9</title></head><body>"
             b"<p>The dashboard is not built yet. Run: pnpm -C web build</p></body></html>")

# Same rule `phoenix project new` uses (phoenix9/project.py NAME_RE).
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+$")
GATE_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+\.\d+$")  # <run-id>.<n> (used by the gate routes in step 03)


class BadRequest(Exception):
    """The request itself is wrong (answered 400 before any ops call)."""


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
    return app.info()


def get_projects(req):
    return projects.rows()


def get_check_name(req):
    return projects.check_name(req.query.get("name", ""))


def get_project(req, name):
    row = projects.row(check_name(name))
    return {**projects.show(name), **{k: row[k] for k in ("needs_you", "run", "repo_url")}}


def get_changelog(req, name):
    return projects.changelog(check_name(name), limit=int_param(req, "limit", 20))


def get_keys(req, name):
    return keys.rows(check_name(name))


def get_settings(req, name):
    return settings.show(check_name(name))


def get_explain(req, name):
    return settings.explain(check_name(name))


def get_specs(req, name):
    return projects.specs(check_name(name))


def get_builds(req, name):
    return runs.builds(check_name(name))


def get_run(req, project, run_id):
    return runs.detail(check_name(project), check_run_id(run_id))


def get_gates(req):
    name = req.query.get("project")
    return gates.list_(check_name(name) if name else None)


def get_steps(req):
    return library.steps()


def get_profiles(req):
    return library.profiles()


def get_presets(req):
    return library.presets()


def get_templates(req):
    return projects.templates_menu()


def get_services_lib(req):
    return library.services()


def get_repos(req):
    return github.repos()


def get_global(req):
    return app.global_view()


def get_services(req):
    return app.services_view()


NAME = r"(?P<name>[^/]+)"
ROUTES = [  # first match wins, so check-name comes before <name>
    ("GET", r"/api/info", get_info),
    ("GET", r"/api/projects", get_projects),
    ("GET", r"/api/projects/check-name", get_check_name),
    ("GET", rf"/api/projects/{NAME}", get_project),
    ("GET", rf"/api/projects/{NAME}/changelog", get_changelog),
    ("GET", rf"/api/projects/{NAME}/keys", get_keys),
    ("GET", rf"/api/projects/{NAME}/settings", get_settings),
    ("GET", rf"/api/projects/{NAME}/explain", get_explain),
    ("GET", rf"/api/projects/{NAME}/specs", get_specs),
    ("GET", rf"/api/projects/{NAME}/runs", get_builds),
    ("GET", r"/api/runs/(?P<project>[^/]+)/(?P<run_id>[^/]+)", get_run),
    ("GET", r"/api/gates", get_gates),
    ("GET", r"/api/library/steps", get_steps),
    ("GET", r"/api/library/profiles", get_profiles),
    ("GET", r"/api/library/presets", get_presets),
    ("GET", r"/api/library/templates", get_templates),
    ("GET", r"/api/library/services", get_services_lib),
    ("GET", r"/api/github/repos", get_repos),
    ("GET", r"/api/global", get_global),
    ("GET", r"/api/services", get_services),
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
            pass
        except Exception:
            api_log(traceback.format_exc())
            self.fail(500, SERVER_ERROR)
        finally:
            api_log(f"{method} {self.path_only} {self.status} {(time.monotonic() - started) * 1000:.0f}ms")

    def dispatch(self, method):
        if method == "POST":
            if not self.guard_ok():
                return self.fail(403, "Refused: this request didn't come from the Phoenix dashboard.")
            if self.read_body() is None:
                return
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
    httpd.write_lock = threading.Lock()   # one write at a time (step 03)
    httpd.stopping = threading.Event()
    httpd.jobs = {}                       # background jobs by id (step 03)
    httpd.web_dist = Path(web_dist) if web_dist else paths.library() / "web" / "dist"
    return httpd
