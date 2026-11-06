"""Dashboard addresses (B2/B2b): dashboard_url, allowed_origins and vscode_url as global settings, kept in step
with api.env, read by the API, checked by the doctor, and the one-time migration."""
import json
import tomllib

import pytest

from phoenix9 import addresses, doctor, events, paths, project, updater
from phoenix9.__main__ import main
from phoenix9.api import server
from phoenix9.ops import app, common
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

NEW = "https://phoenix.rebirthwebdesign.com.au"
OLD = "https://files.rebirthwebdesign.com.au"


@pytest.fixture
def fakes(adapters, monkeypatch):
    monkeypatch.delenv("PHOENIX_API_ORIGINS", raising=False)
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def api_env(text):
    paths.config().mkdir(parents=True, exist_ok=True)
    addresses.api_env_path().write_text(text)


def restarts(adapters):
    return [c for c in adapters.host.calls if c[:2] == ["systemctl", "restart"]]


def global_toml() -> dict:
    return tomllib.loads((paths.config() / "global.toml").read_text())


def test_defaults_without_any_setting():
    assert addresses.read() == {"dashboard_url": "https://phoenix.rebirthwebdesign.com.au/",
                                "allowed_origins": [NEW], "vscode_url": ""}
    assert addresses.origin_of("https://x.test:8443/proxy/8095/") == "https://x.test:8443"


def test_set_origins_rewrites_api_env_and_restarts_the_api(fakes, capsys):
    api_env(f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={OLD}\n")
    code, out, _ = run_cmd(capsys, "settings", "global", "set", f"allowed_origins={NEW}/,{OLD}", "--who", "alex")
    assert code == 0 and "API restart asked" in out
    assert global_toml()["dashboard"]["allowed_origins"] == [NEW, OLD]
    assert addresses.api_env_path().read_text() == f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={NEW},{OLD}\n"
    assert restarts(fakes) == [["systemctl", "restart", "--no-block", "phoenix-api"]]
    assert "settings global set allowed_origins" in (paths.logs() / "commands.jsonl").read_text()
    changed = [e for e in events.read(paths.events()) if e["type"] == "settings.changed"]
    assert changed[-1]["data"]["keys"] == ["allowed_origins"] and changed[-1]["project"] is None


def test_unchanged_origins_do_not_restart(fakes, capsys):
    api_env(f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={NEW}\n")
    code, out, _ = run_cmd(capsys, "settings", "global", "set", "vscode_url=https://code.example.test/")
    assert code == 0 and restarts(fakes) == [] and "API restart not needed" in out


def test_bad_values_are_refused(fakes, capsys):
    code, _, err = run_cmd(capsys, "settings", "global", "set", "dashboard_url=ftp://nope")
    assert code == 1 and "http or https" in err
    code, _, err = run_cmd(capsys, "settings", "global", "set", "colour=red")
    assert code == 1 and "not a dashboard address setting" in err
    code, _, err = run_cmd(capsys, "settings", "global", "set", "allowed_origins=")
    assert code == 1 and "at least one" in err
    assert not (paths.config() / "global.toml").exists() and restarts(fakes) == []


def test_global_show(fakes, capsys):
    code, out, _ = run_cmd(capsys, "settings", "global", "show", "--json")
    assert code == 0 and json.loads(out)["addresses"]["dashboard_url"] == "https://phoenix.rebirthwebdesign.com.au/"
    code, out, _ = run_cmd(capsys, "settings", "global", "show")
    assert "vscode_url = (not set)" in out


def test_vscode_links_use_the_setting(fakes, phoenix_env):
    (phoenix_env["projects"] / "alpha").mkdir()
    gone = project.vscode_link("alpha")
    assert gone == {"url": None, "reason": "Set the VS Code address in Global settings."}
    addresses.save({"vscode_url": "https://code.example.test/"})
    assert project.vscode_link("alpha") == {"url": f"https://code.example.test/?folder={phoenix_env['projects'] / 'alpha'}",
                                            "reason": None}


def test_api_reads_origins_from_the_setting_when_env_has_none(fakes):
    assert server.allowed_origins() == [NEW]
    addresses.save({"allowed_origins": ["http://a.test"]})
    assert server.allowed_origins() == ["http://a.test"]


def test_refusal_names_the_origin_and_where_to_allow_it(fakes, api):
    status, body = api("/api/global/addresses", "POST", {**POST_HEADERS, "Origin": "https://evil.test"},
                       {"vscode_url": "https://x.test/"})
    assert status == 403
    assert body["message"] == ("Refused: this page was opened from https://evil.test, which Phoenix doesn't allow "
                               "yet. Add it in Global settings > Dashboard addresses (or run `phoenix settings "
                               "global set allowed_origins=...`).")
    status, body = api("/api/global/addresses", "POST", {"Origin": NEW}, {})
    assert status == 403 and "didn't come from the Phoenix dashboard" in body["message"]


def test_api_writes_addresses_and_reads_them_back(api, fakes):
    status, body = api("/api/global/addresses", "POST", POST_HEADERS,
                       {"vscode_url": "https://code.example.test/", "allowed_origins": [NEW, OLD]})
    assert status == 200 and body["data"]["values"]["vscode_url"] == "https://code.example.test/"
    assert body["data"]["api_restart"] == "asked"
    assert api("/api/global")[1]["data"]["addresses"]["allowed_origins"] == [NEW, OLD]
    assert api("/api/info")[1]["data"]["dashboard_url"] == "https://phoenix.rebirthwebdesign.com.au/"
    assert api("/api/info")[1]["data"]["vscode_url"] == "https://code.example.test/"
    status, body = api("/api/global/addresses", "POST", POST_HEADERS, {"dashboard_url": "nope"})
    assert status == 400 and "http or https" in body["message"]


def test_health_reports_the_running_origins(api, fakes):
    assert api("/api/health")[1]["data"]["origins"] == [NEW]


def check_origins(adapters, served):
    adapters.http.script("GET", "http://127.0.0.1:8095/api/health", 200,
                         body=json.dumps({"ok": True, "data": {"ok": True, "origins": served}}).encode())
    return doctor.check_origins(doctor.Context(adapters, "quick"))


def test_doctor_compares_the_running_origins_with_the_setting(fakes):
    ok, detail, _ = check_origins(fakes, [NEW])
    assert ok and NEW in detail
    ok, detail, fix = check_origins(fakes, [OLD])
    assert not ok and f"the running API allows {OLD}" in detail and f"the setting says {NEW}" in detail
    assert "phoenix service restart api" in fix
    assert "origins" in doctor.CHECKS_BY_MODE["quick"] and "origins" in doctor.CHECKS_BY_MODE["full"]


def test_migration_keeps_old_origins_and_adds_the_dashboard(fakes):
    api_env(f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={OLD}\n")
    done = addresses.migrate_once()
    assert done == {"allowed_origins": [OLD, NEW], "api_env_changed": True}
    assert global_toml()["dashboard"]["allowed_origins"] == [OLD, NEW]
    assert f"PHOENIX_API_ORIGINS={OLD},{NEW}" in addresses.api_env_path().read_text()
    assert addresses.migrate_once() is None                      # one time only


def test_migrate_command_restarts_the_api_only_when_it_changed_something(fakes, capsys):
    api_env(f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={OLD}\n")
    code, out, _ = run_cmd(capsys, "settings", "global", "migrate", "--json")
    assert code == 0 and json.loads(out)["migrated"] is True
    assert restarts(fakes) == [["systemctl", "restart", "--no-block", "phoenix-api"]]
    code, out, _ = run_cmd(capsys, "settings", "global", "migrate", "--json")
    assert json.loads(out)["migrated"] is False and len(restarts(fakes)) == 1


def test_api_start_migrates_and_uses_the_new_origins(fakes, monkeypatch):
    api_env(f"PHOENIX_API_PORT=8095\nPHOENIX_API_ORIGINS={OLD}\n")
    monkeypatch.setenv("PHOENIX_API_ORIGINS", OLD)            # what systemd handed the process
    server.migrate_addresses()
    assert server.allowed_origins() == [OLD, NEW] and restarts(fakes) == []


def test_global_view_and_info_carry_the_addresses(fakes):
    assert app.global_view()["addresses"]["vscode_url"] == ""
    assert app.info()["dashboard_url"] == "https://phoenix.rebirthwebdesign.com.au/"


def test_no_hard_coded_addresses_left():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for rel in ("phoenix9", "deploy", "web/src"):
        for path in (root / rel).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".sh", ".ts", ".tsx", ".service") \
                    and path.name != "addresses.py" and ".test." not in path.name and "test" not in path.parts:
                assert "files.rebirthwebdesign" not in path.read_text(errors="ignore"), path
    assert not hasattr(paths, "VSCODE_URL")
