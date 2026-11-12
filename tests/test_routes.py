"""Tests for the route catalogue: Python and TypeScript lists agree, and every check refuses what it should."""
import re
from pathlib import Path

import pytest

from phoenix9 import paths, routes
from phoenix9.ops import common
from test_ops_logs import RUN, proj  # noqa: F401  (fixture)
from test_gates import make_run, open_one

TS = Path(__file__).resolve().parent.parent / "web/src/lib/routes.ts"


def ts_routes():
    """The (name, params) pairs written one per line in routes.ts."""
    found = []
    for line in TS.read_text().splitlines():
        m = re.match(r'\s*\{ name: "([^"]+)", params: \[([^\]]*)\] \},', line)
        if m:
            found.append((m.group(1), re.findall(r'"([^"]+)"', m.group(2))))
    return found


def test_python_and_ts_lists_match():
    assert ts_routes() == [(n, p) for n, p in routes.ROUTES] and len(ts_routes()) == 8


def test_simple_routes(proj):
    assert routes.resolve("projects", {}) == {"hash": "#/", "label": "Projects"}
    assert routes.resolve("projects", {"q": "a b", "attention": "1"})["hash"] == "#/?q=a%20b&attention=1"
    assert routes.resolve("new")["hash"] == "#/new"
    assert routes.resolve("settings", {"section": "models"}) == {"hash": "#/settings?section=models", "label": "Settings › Models"}


def test_unknown_route_and_param(proj):
    for bad in ("nope", "p/demo/nope", "p//build", "p/demo/build/x"):
        with pytest.raises(common.OpsError, match="not a page"):
            routes.resolve(bad)
    with pytest.raises(common.OpsError, match="no param 'zzz'"):
        routes.resolve("new", {"zzz": 1})


def test_project_must_exist(proj):
    with pytest.raises(common.NotFound, match="ghost"):
        routes.resolve("p/ghost/overview")
    assert routes.resolve("p/demo/overview") == {"hash": "#/p/demo/overview", "label": "demo › Overview"}


def test_run_and_wizard(proj):
    got = routes.resolve("p/demo/build", {"run": RUN, "wizard": 3})
    assert got["hash"] == f"#/p/demo/build?run={RUN}&wizard=3"
    with pytest.raises(common.NotFound, match="no build"):
        routes.resolve("p/demo/build", {"run": "nope"})
    (paths.runs("demo") / "logs").mkdir(exist_ok=True)
    for bad in ("..", ".", "logs", f"{RUN}/..", f"../demo/{RUN}", "20260101-000000-Demo"):
        with pytest.raises(common.NotFound, match="no build"):
            routes.resolve("p/demo/build", {"run": bad})
    for bad in (0, 8, "x"):
        with pytest.raises(common.OpsError, match="slides 1 to 7"):
            routes.resolve("p/demo/build", {"wizard": bad})


def test_gate_must_be_open(proj, tmp_path):
    with pytest.raises(common.NotFound, match="open gate"):
        routes.resolve("p/demo/overview", {"gate": "x.1"})


def test_gate_open(phoenix_env, tmp_path):
    (phoenix_env["projects"] / "alpha").mkdir()
    gate = open_one(make_run(tmp_path))
    assert routes.resolve("p/alpha/overview", {"gate": gate["id"]})["hash"] == f"#/p/alpha/overview?gate={gate['id']}"


def test_log_must_exist(proj):
    log = f"{RUN}/logs/builder.log"
    got = routes.resolve("p/demo/logs", {"log": log, "kind": "step"})
    assert got["hash"] == f"#/p/demo/logs?kind=step&log={log.replace('/', '%2F')}"
    with pytest.raises(common.NotFound, match="no log"):
        routes.resolve("p/demo/logs", {"log": "nope"})


def test_settings_key_and_section(proj):
    got = routes.resolve("p/demo/settings", {"section": "build", "key": "max_tries"})
    assert got == {"hash": "#/p/demo/settings?section=build&key=max_tries", "label": "demo › Settings › Build"}
    with pytest.raises(common.OpsError, match="not a project setting"):
        routes.resolve("p/demo/settings", {"key": "bogus"})
    with pytest.raises(common.OpsError, match="not a settings section"):
        routes.resolve("p/demo/settings", {"section": "models"})
    with pytest.raises(common.OpsError, match="not a settings section"):
        routes.resolve("settings", {"section": "build"})
