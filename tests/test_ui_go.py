"""Tests for ops.ui.go, `phoenix ui go` and POST /api/ui/go."""
import json

import pytest

from phoenix9 import events, paths
from phoenix9.__main__ import main
from phoenix9.ops import common, ui
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)
from test_ops_logs import proj  # noqa: F401  (fixture)


def _ui_events() -> list[dict]:
    return [e for e in events.read(paths.events()) if e["type"] == "ui.go"]


def test_go_writes_event(proj):
    found = ui.go("projects", {"q": "shop", "status": "running"}, "agent")
    assert found == {"hash": "#/?q=shop&status=running", "label": "Projects"}
    (ev,) = _ui_events()
    assert ev["data"] == {"hash": "#/?q=shop&status=running", "label": "Projects", "by": "agent"}
    assert ev["project"] is None
    assert any(e["type"] == "command" and e["data"]["who"] == "agent" for e in events.read(paths.events()))


def test_go_refuses_bad_route(proj):
    for to, params in (("nope", {}), ("settings", {"zzz": "1"}), ("p/missing/build", {}), ("settings", {"section": "x"})):
        with pytest.raises(common.OpsError):
            ui.go(to, params, "agent")
    assert _ui_events() == []


def test_cli(proj, capsys):
    assert main(["ui", "go", "settings", "--param", "section=models"]) == 0
    assert capsys.readouterr().out.strip() == "Moved the dashboard to Settings › Models"
    assert main(["ui", "go", "new", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["hash"] == "#/new"
    assert [e["data"]["hash"] for e in _ui_events()] == ["#/settings?section=models", "#/new"]


def test_cli_refused(proj, capsys):
    assert main(["ui", "go", "nope"]) == 1
    assert "not a page" in capsys.readouterr().err
    assert main(["ui", "go", "settings", "--param", "bad"]) == 1
    assert _ui_events() == []


def test_api_route(api):
    make_project("alpha")
    status, body = api("/api/ui/go", "POST", POST_HEADERS, {"to": "p/alpha/build", "params": {"wizard": "2"}})
    assert status == 200 and body["data"]["hash"] == "#/p/alpha/build?wizard=2"
    assert _ui_events()[-1]["data"]["by"] == "agent"
    for bad in ({"to": "nope"}, {"to": "projects", "params": {"x": "1"}}, {"to": "projects", "params": 3}, {}):
        status, body = api("/api/ui/go", "POST", POST_HEADERS, bad)
        assert status == 400 and body["ok"] is False and body["message"]
    assert len(_ui_events()) == 1
