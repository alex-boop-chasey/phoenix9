"""Tests for the dashboard API server: read endpoints, the write guard, static files and the serve command."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from phoenix9 import paths, settings
from phoenix9.__main__ import main
from phoenix9.api import server
from phoenix9.ops import common, projects

ORIGIN = "https://files.rebirthwebdesign.com.au"
POST_HEADERS = {"X-Phoenix": "1", "Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def dist(tmp_path):
    """A small fake web/dist folder."""
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>app</html>")
    (folder / "assets" / "app.js").write_text("console.log(1)")
    (folder / "assets" / "app.css").write_text("body{}")
    (tmp_path / "secret.txt").write_text("outside")
    return folder


@pytest.fixture
def api(tmp_path, monkeypatch, dist):
    """A running API server on a free port, with fake adapters; returns a request function."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(tmp_path / "claude.json"))
    fakes.host.files[str(tmp_path / "claude.json")] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    httpd = server.make_server(0, web_dist=dist)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, method="GET", headers=None, body=None, raw=False):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError as err:
            resp = err
        content = resp.read()
        resp.close()
        return (resp.status, resp, content) if raw else (resp.status, json.loads(content))

    call.base = base
    yield call
    httpd.shutdown()
    httpd.server_close()


def make_project(name):
    folder = paths.projects() / name
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text(f"# {name}\n\nAbout {name}.\n\n- Profile: python-script\n- Repo: (none yet)\n")
    settings.save_project(folder, {})
    return folder


def test_info_ok_shape(api):
    status, body = api("/api/info")
    assert status == 200 and body["ok"] is True
    assert {"version", "update", "github", "services"} <= set(body["data"])


def test_json_headers(api):
    status, resp, _ = api("/api/info", raw=True)
    assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
    assert resp.headers["Cache-Control"] == "no-store"


def test_projects_rows(api):
    make_project("alpha")
    make_project("beta")
    status, body = api("/api/projects")
    assert status == 200
    rows = body["data"]
    assert [r["name"] for r in rows] == ["alpha", "beta"]
    assert {"needs_you", "run", "repo_url", "harness"} <= set(rows[0])


def test_project_show(api):
    make_project("alpha")
    status, body = api("/api/projects/alpha")
    assert status == 200
    data = body["data"]
    assert data["name"] == "alpha" and data["needs_you"] == 0 and data["run"] is None


def test_project_sub_endpoints(api):
    make_project("alpha")
    for tail in ("changelog?limit=5", "keys", "settings", "explain", "specs", "runs"):
        status, body = api(f"/api/projects/alpha/{tail}")
        assert status == 200 and body["ok"], tail


def test_unknown_project_404(api):
    status, body = api("/api/projects/nothing")
    assert status == 404 and body["ok"] is False and "nothing" in body["message"]


def test_bad_project_name_400_never_calls_ops(api, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("ops was called")
    for fn in ("row", "show", "rows", "changelog"):
        monkeypatch.setattr(projects, fn, boom)
    for path in ("/api/projects/Bad_Name", "/api/projects/-x", "/api/projects/Bad/changelog",
                 "/api/gates?project=Bad_Name"):
        status, body = api(path)
        assert status == 400 and body["ok"] is False, path


def test_check_name_route_not_taken_as_project(api):
    status, body = api("/api/projects/check-name?name=fresh-one")
    assert status == 200 and body["data"]["ok"] is True
    status, body = api("/api/projects/check-name?name=Bad_Name")
    assert status == 200 and body["data"]["ok"] is False


def test_bad_run_id_400(api):
    make_project("alpha")
    status, body = api("/api/runs/alpha/not-a-run")
    assert status == 400 and body["ok"] is False
    status, body = api("/api/runs/alpha/20260101-000000-nope")
    assert status == 404


def test_gates_list_filtered_by_project(api):
    make_project("alpha")
    status, body = api("/api/gates")
    assert status == 200 and body["data"] == []
    status, body = api("/api/gates?project=alpha")
    assert status == 200 and body["data"] == []
    status, body = api("/api/gates?project=missing")
    assert status == 404


def test_library_endpoints(api):
    status, body = api("/api/library/steps")
    assert status == 200 and "steps" in body["data"] and "problems" in body["data"]
    assert "profiles" in api("/api/library/profiles")[1]["data"]
    assert "presets" in api("/api/library/presets")[1]["data"]
    assert isinstance(api("/api/library/templates")[1]["data"], list)
    assert "services" in api("/api/library/services")[1]["data"]
    assert "supported" in api("/api/services")[1]["data"]
    assert "values" in api("/api/global")[1]["data"]
    assert "connected" in api("/api/github/repos")[1]["data"]


def test_library_presets_list_their_step_switches(api):
    rows = {p["name"]: p for p in api("/api/library/presets")[1]["data"]["presets"]}
    assert rows["full"]["steps"]["reviewer"] is True
    assert rows["quick"]["steps"] == {"planner": False, "check-writer": False, "verify": True, "reviewer": False}
    assert rows["custom"]["steps"] == {}


def test_post_without_header_403(api):
    status, body = api("/api/anything", "POST", {"Origin": ORIGIN}, {})
    assert status == 403 and body["ok"] is False and "Phoenix dashboard" in body["message"]


def test_post_foreign_origin_403(api):
    status, _ = api("/api/anything", "POST", {"X-Phoenix": "1", "Origin": "https://evil.example"}, {})
    assert status == 403


def test_post_origin_list_from_env(api, monkeypatch):
    headers = {"X-Phoenix": "1", "Origin": "http://other.test"}
    assert api("/api/anything", "POST", headers, {})[0] == 403
    monkeypatch.setenv("PHOENIX_API_ORIGINS", "http://x.test, http://other.test")
    assert api("/api/anything", "POST", headers, {})[0] == 404  # passes the guard, no route
    assert api("/api/anything", "POST", POST_HEADERS, {})[0] == 403  # default origin no longer listed


def test_post_passing_guard_without_route_404(api):
    status, body = api("/api/anything", "POST", POST_HEADERS, {})
    assert status == 404 and body["ok"] is False


def test_post_body_not_json_400(api):
    assert api("/api/anything", "POST", POST_HEADERS, b"{nope")[0] == 400
    assert api("/api/anything", "POST", POST_HEADERS, b"[1, 2]")[0] == 400


def test_post_body_too_big_400(api):
    status, body = api("/api/anything", "POST", POST_HEADERS, b'{"a": "' + b"x" * 70000 + b'"}')
    assert status == 400 and "too big" in body["message"]


def test_unexpected_error_500_no_traceback_in_reply_and_logged(api, monkeypatch):
    def boom():
        raise RuntimeError("kaboom-detail")
    monkeypatch.setattr(projects, "rows", boom)
    status, resp, content = api("/api/projects", raw=True)
    assert status == 500
    text = content.decode()
    assert "Something went wrong; details are in the API log." in text
    assert "Traceback" not in text and "kaboom" not in text
    log = (paths.logs() / "api.log").read_text()
    assert "Traceback" in log and "kaboom-detail" in log
    assert "GET /api/projects 500" in log


def test_static_index_and_asset_content_types(api):
    status, resp, content = api("/", raw=True)
    assert status == 200 and content == b"<html>app</html>"
    assert resp.headers["Content-Type"].startswith("text/html") and resp.headers["Cache-Control"] == "no-store"
    assert api("/index.html", raw=True)[0] == 200
    _, resp, _ = api("/assets/app.css", raw=True)
    assert resp.headers["Content-Type"].startswith("text/css")
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    _, resp, _ = api("/assets/app.js", raw=True)
    assert "javascript" in resp.headers["Content-Type"]


def test_static_traversal_refused(api):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/assets/%00x"):
        status, body = api(path)
        assert status == 404 and body["ok"] is False, path


def test_not_built_page_when_dist_missing(api, dist):
    (dist / "index.html").unlink()
    status, resp, content = api("/", raw=True)
    assert status == 200 and b"pnpm -C web build" in content


def test_unknown_path_404_json(api):
    for path in ("/nope", "/api/nope"):
        status, body = api(path)
        assert status == 404 and body["ok"] is False


def test_server_binds_localhost_only(tmp_path):
    httpd = server.make_server(0, web_dist=tmp_path)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
        assert httpd.daemon_threads and httpd.jobs == {} and not httpd.stopping.is_set()
    finally:
        httpd.server_close()
    with pytest.raises(ValueError):
        server.make_server(0, host="0.0.0.0")


def test_cli_api_serve_refuses_public_host(capsys):
    assert main(["api", "serve", "--host", "0.0.0.0"]) == 1
    assert "127.0.0.1" in capsys.readouterr().err + ""


def test_cli_api_serve_starts_and_stops(capsys, monkeypatch):
    stops = []
    real = server.make_server

    def make(port, host="127.0.0.1", web_dist=None):
        httpd = real(port, host, web_dist)
        stops.append(httpd)
        httpd.stopping.set()  # stop right away
        return httpd
    monkeypatch.setattr(server, "make_server", make)
    assert main(["api", "serve", "--port", "0"]) == 0
    assert "Phoenix API listening on http://127.0.0.1:" in capsys.readouterr().out


def test_only_ops_imported():
    import re
    source = open(server.__file__, encoding="utf-8").read()
    assert "subprocess" not in source
    imported = set()
    for line in re.findall(r"^from phoenix9(?:\.(\w+))? import (.+)$", source, re.M):
        pkg, names = line
        imported |= {pkg} if pkg else {n.strip() for n in names.split(",")}
    assert imported <= {"ops", "paths", "scrub", "atomic", "api"}  # api = its own stream helper


def test_projects_query_params(api):
    make_project("alpha")
    make_project("beta")
    status, body = api("/api/projects?q=ALPHA&attention=1&sort=size")
    assert status == 200
    data = body["data"]
    assert [r["name"] for r in data["rest"]] == ["alpha"] and data["top"] == [] and data["total"] == 1
    assert data["counts"]["all"] == 1
    status, body = api("/api/projects?status=idle&owner=none")
    assert status == 200 and body["data"]["total"] == 2


def test_projects_query_bad_values_are_400(api):
    for tail in ("status=bogus", "sort=bogus", "attention=maybe"):
        status, body = api(f"/api/projects?{tail}")
        assert status == 400 and body["ok"] is False
