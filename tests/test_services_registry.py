"""The services registry: list, connect (with check), disconnect, and the CLI around them."""
import io
import json

import pytest

from phoenix9 import keys, paths, services
from phoenix9.__main__ import build_parser, main
from phoenix9.ops import common
from phoenix9.ops import services as ops

SENTINEL = "sk-SENTINEL-123"
CHECK_URL = "http://proxy.fake/supabase/v1/projects"


@pytest.fixture
def fakes(adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    return adapters


def files_text(home):
    return "".join(p.read_text() for p in home.rglob("*") if p.is_file() and p.parent.name != "secrets")


def test_list_shows_names_never_values(capsys, fakes):
    ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    capsys.readouterr()
    assert main(["services", "list"]) == 0
    plain = capsys.readouterr()
    assert "Supabase: connected, key checked OK" in plain.out and "Stripe: no account connection" in plain.out
    assert main(["services", "list", "--json"]) == 0
    js = capsys.readouterr()
    rows = {r["name"]: r for r in json.loads(js.out)}
    assert len(rows) == 10 and rows["supabase"]["account_keys"] == ["SUPABASE_ACCESS_TOKEN"]
    assert rows["stripe"]["connected"] is True and rows["github"]["connected"] is False
    assert SENTINEL not in plain.out + plain.err + js.out + js.err


def test_connect_writes_secret_and_registry(fakes, phoenix_env):
    r = ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    assert r["checked"] == "ok"
    assert keys.read_secret_file("service-supabase.env") == {"SUPABASE_ACCESS_TOKEN": SENTINEL}
    entry = services.read_registry()["supabase"]
    assert entry["connected"] is True and entry["checked"] == "ok" and entry["account_keys"] == ["SUPABASE_ACCESS_TOKEN"]
    assert fakes.http.calls[0]["headers"]["X-Phoenix-Proxy-Token"] == "fake-proxy-token"
    assert SENTINEL not in files_text(phoenix_env["home"])
    spec, key = ops.proxy_spec_for("supabase")
    assert spec.service == "supabase" and key == SENTINEL


def test_connect_check_failure_keeps_key_and_reports(fakes):
    fakes.http.script("GET", CHECK_URL, 401)
    r = ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    assert r["message"] == "Supabase: saved, but Supabase refused it: HTTP 401."
    assert services.read_registry()["supabase"]["checked"] == "failed: HTTP 401"
    assert keys.read_secret_file("service-supabase.env")


def test_connect_proxy_has_only_check_rule_and_is_stopped(fakes):
    ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    started = fakes.proxy.started[0]
    assert [(r.method, r.path) for r in started["rules"]] == [("GET", "/v1/projects")]
    assert started["bind"] == "127.0.0.1" and started["step"] == "services-connect"
    assert fakes.proxy.running() == []

    def boom(*a, **k):
        raise RuntimeError("down")
    fakes.http.request = boom
    r = ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    assert r["checked"].startswith("failed") and fakes.proxy.running() == []


def test_connect_keys_only_service_refused(fakes):
    with pytest.raises(common.OpsError, match="Stripe needs no account connection; add its keys per project"):
        ops.connect("stripe", {"X": SENTINEL}, who="cli")


def test_connect_wrong_key_names_refused(fakes):
    with pytest.raises(common.OpsError, match="missing SUPABASE_ACCESS_TOKEN.*not wanted OTHER"):
        ops.connect("supabase", {"OTHER": SENTINEL}, who="cli")
    assert not (paths.secrets() / "service-supabase.env").exists()


def test_disconnect_requires_yes_and_warns_users(fakes, phoenix_env):
    ops.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="cli")
    folder = phoenix_env["projects"] / "demo"
    folder.mkdir()
    (folder / "phoenix.toml").write_text('services = ["supabase"]\n')
    with pytest.raises(common.OpsError, match="--yes"):
        ops.disconnect("supabase", who="cli", yes=False)
    assert (paths.secrets() / "service-supabase.env").exists()
    r = ops.disconnect("supabase", who="cli", yes=True)
    assert r["used_by"] == ["demo"] and "demo" in r["warning"]
    assert not (paths.secrets() / "service-supabase.env").exists()
    assert "supabase" not in services.read_registry()
    with pytest.raises(common.OpsError, match="not connected"):
        ops.proxy_spec_for("supabase")


def test_cli_connect_from_stdin_never_echoes(capsys, fakes, monkeypatch, phoenix_env):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"SUPABASE_ACCESS_TOKEN={SENTINEL}\n"))
    assert main(["services", "connect", "supabase", "--from-stdin"]) == 0
    out = capsys.readouterr()
    assert "connected, key checked OK" in out.out and SENTINEL not in out.out + out.err
    assert SENTINEL not in files_text(phoenix_env["home"])
    assert "services connect supabase" in (paths.logs() / "commands.jsonl").read_text()


def test_cli_rejects_value_as_argument(capsys):
    assert main(["services", "connect", "supabase", "--token", SENTINEL]) == 2
    assert SENTINEL not in capsys.readouterr().out
    sub = build_parser()._subparsers._group_actions[0].choices["services"]._subparsers._group_actions[0]
    connect = sub.choices["connect"]
    valued = [a.option_strings for a in connect._actions if a.option_strings and a.nargs != 0
              and a.metavar not in (None, "PATH") and a.dest not in ("help",)]
    assert valued == []
    assert [a.option_strings for a in connect._actions if a.metavar == "PATH"] == [["--from-file"]]
