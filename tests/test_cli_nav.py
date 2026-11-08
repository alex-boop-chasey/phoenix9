"""Tests for `phoenix nav` and the dashboard address order (env, saved, default)."""
import json

from phoenix9 import addresses
from phoenix9.__main__ import main
from phoenix9.ops import app
from test_ops_logs import proj  # noqa: F401  (fixture)


def test_dashboard_url_order(proj, monkeypatch, tmp_path):
    monkeypatch.delenv("PHOENIX_DASHBOARD_URL", raising=False)
    assert app.info()["dashboard_url"] == addresses.DEFAULT_DASHBOARD_URL
    addresses.save({"dashboard_url": "https://saved.example.com/"})
    assert app.dashboard_url() == "https://saved.example.com/"
    monkeypatch.setenv("PHOENIX_DASHBOARD_URL", "https://env.example.com/")
    assert app.info()["dashboard_url"] == "https://env.example.com/"
    monkeypatch.setenv("PHOENIX_DASHBOARD_URL", "not a url")
    assert app.dashboard_url() == "https://saved.example.com/"


def test_nav_plain(proj, monkeypatch, capsys):
    monkeypatch.setenv("PHOENIX_DASHBOARD_URL", "https://dash.example.com")
    assert main(["nav", "settings", "--param", "section=models"]) == 0
    lines = capsys.readouterr().out.strip().split("\n")
    assert lines[0] == "Settings › Models"
    assert lines[1] == "https://dash.example.com/#/settings?section=models"
    assert lines[2] == "```phoenix-nav" and lines[4] == "```"
    body = json.loads(lines[3])
    assert body == {"v": 1, "links": [{"to": "settings", "params": {"section": "models"}, "label": "Settings › Models"}]}
    assert lines[5] == "Open Settings › Models: https://dash.example.com/#/settings?section=models"


def test_nav_json(proj, monkeypatch, capsys):
    monkeypatch.setenv("PHOENIX_DASHBOARD_URL", "https://dash.example.com/")
    assert main(["nav", "new", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["link"] == "https://dash.example.com/#/new" and out["label"] == "New project"


def test_nav_refused(proj, capsys):
    assert main(["nav", "nope"]) == 1
    assert "not a page" in capsys.readouterr().err
    assert main(["nav", "settings", "--param", "bad"]) == 1
    assert main(["nav", "settings", "--param", "zzz=1"]) == 1


def test_nav_check(proj, capsys):
    assert main(["nav", "projects", "--check"]) == 0
    assert capsys.readouterr().out.strip() == "ok"
    assert main(["nav", "p/missing/build", "--check"]) == 1
    captured = capsys.readouterr()
    assert "ok" not in captured.out and captured.err.strip()
