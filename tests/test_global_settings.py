"""Phoenix settings backend: Claude/Telegram rows, account settings, connection test, default models, health, history."""
import json
import tomllib

from phoenix9 import paths, services as lib, settings, updater
from phoenix9.ops import app, common, services as ops
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

SECRET = "sk-SENTINEL-abcd"
CHECK_URL = "http://proxy.fake/resend/domains"


def test_service_files_with_account_settings_load():
    assert lib.load_problems() == []
    assert [s["name"] for s in lib.get("resend")["account_settings"]] == ["send_from"]


def test_global_services_lists_claude_and_telegram(api):
    status, body = api("/api/global/services")
    names = [r["name"] for r in body["data"]["services"]]
    assert status == 200 and names[0] == "claude" and names[-1] == "telegram" and "github" in names
    claude = body["data"]["services"][0]
    assert claude["connected"] is False and claude["endpoints"]["test"] == "services/claude/test"


def test_connect_telegram_saves_setting_and_shows_ends_in(api):
    status, body = api("/api/services/telegram/connect", "POST", POST_HEADERS,
                       {"values": {"TELEGRAM_BOT_TOKEN": SECRET}, "settings": {"chat_id": "581"}})
    assert status == 200 and SECRET not in json.dumps(body)
    row = {r["name"]: r for r in api("/api/global/services")[1]["data"]["services"]}["telegram"]
    assert row["connected"] and row["ends_in"] == {"TELEGRAM_BOT_TOKEN": "…abcd"}
    assert row["account_settings"][0]["value"] == "581" and SECRET not in json.dumps(row)


def test_saved_service_can_change_a_setting_without_the_key(api, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    ops.connect("resend", {"RESEND_API_KEY": SECRET}, who="t")
    ops.connect("resend", {"RESEND_API_KEY": ""}, who="t", check=False, settings_in={"send_from": "a@b.co"})
    row = {r["name"]: r for r in ops.list_()}["resend"]
    assert row["account_settings"][0]["value"] == "a@b.co" and row["ends_in"] == {"RESEND_API_KEY": "…abcd"}


def test_empty_key_is_refused_when_not_connected():
    try:
        ops.connect("telegram", {"TELEGRAM_BOT_TOKEN": ""}, who="t")
    except common.OpsError as err:
        assert "missing TELEGRAM_BOT_TOKEN" in str(err)
    else:
        raise AssertionError("expected a refusal")


def test_unknown_setting_is_refused():
    try:
        ops.connect("telegram", {"TELEGRAM_BOT_TOKEN": SECRET}, who="t", settings_in={"nope": "x"})
    except common.OpsError as err:
        assert "no setting called 'nope'" in str(err)
    else:
        raise AssertionError("expected a refusal")


def test_test_connection_uses_pasted_key_and_saves_nothing(api, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    status, body = api("/api/services/resend/test", "POST", POST_HEADERS, {"values": {"RESEND_API_KEY": SECRET}})
    assert status == 200 and body["data"]["ok"] is True and SECRET not in json.dumps(body)
    assert not (paths.secrets() / "service-resend.env").exists()
    assert api("/api/services/resend/test", "POST", POST_HEADERS, {"values": {}})[0] == 400
    assert api("/api/services/claude/test", "POST", POST_HEADERS, {"values": {"X": "y"}})[0] == 400


def test_default_models_save_and_apply(api):
    rows = api("/api/global")[1]["data"]["default_models"]
    assert "builder" in rows and rows["builder"]["library"]["model"]
    status, body = api("/api/global/models", "POST", POST_HEADERS,
                       {"steps": {"builder": {"model": "claude-sonnet-5-5", "fallback_models": ["claude-opus-5-5"]}}})
    assert status == 200 and body["data"]["default_models"]["builder"]["model"] == "claude-sonnet-5-5"
    saved = tomllib.loads((paths.config() / "global.toml").read_text())
    assert saved["models"]["builder"] == {"model": "claude-sonnet-5-5", "fallback_models": ["claude-opus-5-5"]}
    assert settings.global_models()["builder"]["fallback_models"] == ["claude-opus-5-5"]
    assert app.global_view()["default_models"]["builder"]["library"] == rows["builder"]["library"]


def test_default_models_refuse_bad_input(api):
    for steps in ({"merge": {"model": "m", "fallback_models": []}},
                  {"builder": {"model": "", "fallback_models": []}},
                  {"builder": {"model": "a", "fallback_models": ["a"]}},
                  {"builder": {"model": "a", "fallback_models": ["b", "c", "d"]}}):
        assert api("/api/global/models", "POST", POST_HEADERS, {"steps": steps})[0] == 400


def test_update_history_lists_newest_first(api):
    assert api("/api/update/history")[1]["data"]["history"] == []
    updater._append_history({"at": "2026-10-30T00:00:00+00:00", "action": "install", "tag": "v9.0", "result": "ok"})
    updater._append_history({"at": "2026-10-31T00:00:00+00:00", "action": "install", "tag": "v9.1", "result": "ok"})
    rows = api("/api/update/history")[1]["data"]["history"]
    assert [r["tag"] for r in rows] == ["v9.1", "v9.0"]


def test_doctor_route_runs_quick_checks(api, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    status, body = api("/api/doctor")
    assert status == 200 and body["data"]["checks"] and body["data"]["checked_at"]
    assert api("/api/doctor?mode=nope")[0] == 400


def test_models_cli_sets_and_lists(capsys):
    from phoenix9.__main__ import main
    assert main(["models", "set", "planner", "claude-opus-5-5", "--fallback", "claude-sonnet-5-5"]) == 0
    capsys.readouterr()
    assert main(["models", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["planner"]["model"] == "claude-opus-5-5" and data["planner"]["fallback_models"] == ["claude-sonnet-5-5"]


def test_services_test_cli(adapters, monkeypatch, capsys):
    from phoenix9.__main__ import main
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", CHECK_URL, 200, body=b"[]")
    ops.connect("resend", {"RESEND_API_KEY": SECRET}, who="t", check=False)
    assert main(["services", "test", "resend"]) == 0
    assert "the key works" in capsys.readouterr().out
