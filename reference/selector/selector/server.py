#!/usr/bin/env python3
"""Project selector: a small web page and JSON API on top of the `proj` command.

Listens on 127.0.0.1:8090 only; Alex reaches it through code-server at /proxy/8090/.
Every read and action runs `proj` (never a shell) and passes on proj's own words.

API (all JSON replies carry {"ok": bool, "message": str}, except the list passthrough):
  GET  /                 the page (index.html)
  GET  /api/projects     `proj list --json` as-is; 502 if proj fails or prints junk
  POST /api/open  {"name"}                    -> proj open <name>   (switch a project back on)
  POST /api/new   {"name", "repo"?: "o/n"}    -> proj new <name> [--repo <o/n>]
Projects are always on, so there is no close action.
POSTs need header `X-Selector: 1` and the right Origin, or they get 403.

Env: PROJ_BIN (default /usr/local/bin/proj), SELECTOR_ORIGIN (default
https://files.rebirthwebdesign.com.au), SELECTOR_TIMEOUT (seconds, default 180).
"""
import json
import os
import re
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8090
MAX_BODY = 10 * 1024
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# Settings are read on each use so tests can change them between requests.
def proj_bin():
    return os.environ.get("PROJ_BIN", "/usr/local/bin/proj")


def allowed_origin():
    return os.environ.get("SELECTOR_ORIGIN", "https://files.rebirthwebdesign.com.au")


def timeout_seconds():
    return float(os.environ.get("SELECTOR_TIMEOUT", "180"))


class ProjError(Exception):
    """proj couldn't be run, or printed something we can't use."""


class ProjTimeout(ProjError):
    """proj took longer than SELECTOR_TIMEOUT and was stopped."""


def run_proj(*args):
    """Run proj with an argument list. Returns (exit code, stdout+stderr stripped)."""
    timeout = timeout_seconds()
    try:
        # Own process group, so a timeout also kills anything proj started (e.g. a git clone).
        proc = subprocess.Popen([proj_bin(), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, start_new_session=True)
    except OSError as e:
        raise ProjError(f"couldn't run proj: {e.strerror or e}")
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise ProjTimeout(f"proj {args[0]} timed out after {timeout:g} seconds and was stopped")
    return proc.returncode, (out or "").strip()


def project_list():
    """The current `proj list --json`, checked to have the shape we need."""
    code, out = run_proj("list", "--json")
    if code != 0:
        raise ProjError(out or f"proj list failed (exit {code})")
    try:
        data = json.loads(out)
        names = [p["name"] for p in data["projects"]]
    except (ValueError, KeyError, TypeError):
        raise ProjError("proj list printed something that isn't the expected project list")
    if not all(isinstance(n, str) for n in names):
        raise ProjError("proj list printed something that isn't the expected project list")
    return data


class BadRequest(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def check_known(name):
    """Name must look right and be in a fresh project list (it may have just been removed)."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BadRequest(400, "That isn't a valid project name.")
    names = [p["name"] for p in project_list()["projects"]]
    if name not in names:
        raise BadRequest(400, f"no project '{name}'")


# Each action takes the validated body and returns the argv for proj.
# They run inside the action lock, so the list check and the command see the same state.
def action_open(body):
    check_known(body.get("name"))
    return ["open", body["name"]]


def action_new(body):
    name, repo = body.get("name"), body.get("repo")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BadRequest(400, "Project names use lowercase letters, digits and dashes "
                              "(start with a letter or digit, up to 41 characters).")
    if repo in (None, ""):
        return ["new", name]
    if not isinstance(repo, str) or not REPO_RE.match(repo):
        raise BadRequest(400, "The GitHub repo should look like owner/name.")
    return ["new", name, "--repo", repo]


ACTIONS = {"/api/open": action_open, "/api/new": action_new}


class Handler(BaseHTTPRequestHandler):
    server_version = "project-selector"

    def send_json(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def reply(self, status, ok, message):
        self.send_json(status, {"ok": ok, "message": message})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    raw = f.read()
            except OSError:
                return self.reply(500, False, "The page file (index.html) is missing.")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
        elif path == "/api/projects":
            try:
                self.send_json(200, project_list())
            except ProjError as e:
                self.reply(502, False, str(e))
        else:
            self.reply(404, False, "Not found.")

    def do_POST(self):
        # Guard against other websites in Alex's browser: browsers won't let them set this
        # header cross-site without our permission, and they can't fake the Origin.
        if self.headers.get("X-Selector") != "1" or self.headers.get("Origin") != allowed_origin():
            return self.reply(403, False, "Refused: this request didn't come from the project page.")
        action = ACTIONS.get(self.path)
        if action is None:
            return self.reply(404, False, "Not found.")
        body = self.read_body()
        if body is None:
            return
        try:
            with self.server.action_lock:  # one action at a time; others wait their turn
                argv = action(body)
                code, out = run_proj(*argv)
        except BadRequest as e:
            return self.reply(e.status, False, e.message)
        except ProjTimeout as e:
            return self.reply(504, False, str(e))
        except ProjError as e:
            return self.reply(502, False, str(e))
        self.reply(200, code == 0, out or ("Done." if code == 0 else f"proj failed (exit {code})"))

    def read_body(self):
        """The JSON object sent with a POST, or None after replying 400."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True  # don't read a body we refuse
            self.reply(400, False, "The request was too big.")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            self.reply(400, False, "The request wasn't valid JSON.")
            return None
        if not isinstance(body, dict):
            self.reply(400, False, "The request should be a JSON object.")
            return None
        return body


def make_server(port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    httpd.daemon_threads = True
    httpd.action_lock = threading.Lock()
    return httpd


def main():
    httpd = make_server(PORT)
    print(f"project-selector listening on http://{HOST}:{PORT}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
