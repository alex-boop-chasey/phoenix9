"""The deployers runner: records, health, rollback, proxy, env file, settings, CLI."""
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from phoenix9 import deploy, events, keys, paths, services, settings
from phoenix9.__main__ import main
from phoenix9.ops import common, deploy as ops_deploy

REAL = Path(__file__).resolve().parent.parent
SENTINEL = "SENTINEL-KEY-31337-deploy"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A temp library: the real steps, presets, profiles and services with the test deployers."""
    root = tmp_path / "lib"
    root.mkdir()
    for name in ("steps", "presets", "profiles", "services", "templates"):
        (root / name).symlink_to(REAL / name)
    (root / "deployers").symlink_to(Path(__file__).parent / "data" / "deployers")
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    return root


def make_project(phoenix_env, with_="scripted", extra=""):
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "code").mkdir()
    (folder / "phoenix.toml").write_text(f'[deploy]\nwith = "{with_}"\nmode = "button"\n\n[deploy.settings]\nlive_port = 8080\n{extra}')
    return folder


class Script:
    """Registers scripted deploy functions as the test deployer's behaviour."""

    def __init__(self, health=((True, "ok"),)):
        self.calls = []
        self.health_answers = list(health)
        self.fail_deploy = None
        self.seen = {}
        self.rollback_args = None

    def install(self):
        sys.modules["deploy_script"] = SimpleNamespace(
            deploy=self.deploy, health=self.health, rollback=self.rollback, preview=self.preview,
            stop_preview=self.stop_preview)

    def deploy(self, dctx):
        self.calls.append("deploy")
        self.seen["dctx"] = dctx
        if dctx.env_file:
            self.seen["env_mode"] = stat.S_IMODE(dctx.env_file.stat().st_mode)
            self.seen["env_path"] = dctx.env_file
        dctx.log(f"using key {SENTINEL}")
        if self.fail_deploy:
            raise deploy.DeployError(self.fail_deploy)
        return {"target": "box", "url": "https://demo.example", "version": "v2", "details": {}}

    def health(self, dctx, result):
        self.calls.append("health")
        return self.health_answers.pop(0) if len(self.health_answers) > 1 else self.health_answers[0]

    def rollback(self, dctx, result, previous):
        self.calls.append("rollback")
        self.rollback_args = (result, previous)
        return {"url": "https://old.example"}

    def preview(self, dctx):
        self.calls.append("preview")
        return {"target": "box", "url": "https://prev.example", "version": "p1", "details": {}}

    def stop_preview(self, dctx, record):
        self.calls.append("stop_preview")


@pytest.fixture
def script():
    s = Script()
    s.install()
    yield s
    sys.modules.pop("deploy_script", None)


def test_none_deployer_skips(phoenix_env, lib, adapters):
    make_project(phoenix_env, "none")
    assert deploy.run_deploy(adapters, "demo", who="t") == {"ok": True, "skipped": "deployer none"}


def test_unsupported_stub_reports_plainly(phoenix_env, lib, adapters):
    make_project(phoenix_env, "stub")
    r = deploy.run_deploy(adapters, "demo", who="t")
    assert r == {"ok": False, "reason": "Stub Cloud is not yet supported"}


def test_deployer_without_health_or_rollback_refused(phoenix_env, lib, adapters):
    make_project(phoenix_env, "nohealth")
    r = deploy.run_deploy(adapters, "demo", who="t")
    assert r["ok"] is False and "every deployer needs a health check and a rollback" in r["reason"]
    assert not deploy.records_path("demo").exists()


def test_healthy_deploy_recorded_event_changelog_notify(phoenix_env, lib, adapters, script):
    folder = make_project(phoenix_env)
    r = deploy.run_deploy(adapters, "demo", who="alex", run_id="r1", commit="abcdef1234567")
    assert r["ok"] and r["url"] == "https://demo.example" and r["kind"] == "deploy" and not r["rolled_back"]
    line = json.loads(deploy.records_path("demo").read_text().splitlines()[-1])
    assert line["commit"] == "abcdef1234567" and line["run"] == "r1" and line["who"] == "alex"
    assert deploy.last_good("demo")["version"] == "v2"
    done = [e for e in events.read(paths.events()) if e["type"] == "deploy.finished"]
    assert done[-1]["data"]["ok"] is True and done[-1]["data"]["url"] == "https://demo.example"
    assert "Deployed abcdef1 to https://demo.example with scripted" in (folder / "notes" / "changelog.md").read_text()
    assert any("https://demo.example" in m for m in adapters.notify.messages)
    assert (paths.runs("demo") / "r1" / "logs" / "deploy.log").exists()


def test_unhealthy_deploy_rolls_back_to_last_good(phoenix_env, lib, adapters, script):
    folder = make_project(phoenix_env)
    deploy.run_deploy(adapters, "demo", who="t", commit="aaaaaaa1")
    script.health_answers = [(False, "502")]
    r = deploy.run_deploy(adapters, "demo", who="t", commit="bbbbbbb2")
    assert r["ok"] is False and r["rolled_back"] is True and "502" in r["reason"]
    result, previous = script.rollback_args
    assert result["version"] == "v2" and previous["commit"] == "aaaaaaa1"
    assert deploy.last_good("demo")["commit"] == "aaaaaaa1"
    assert "Deploy failed, rolled back" in (folder / "notes" / "changelog.md").read_text()


def test_deploy_error_rolls_back(phoenix_env, lib, adapters, script):
    make_project(phoenix_env)
    script.fail_deploy = "build broke"
    r = deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert r["ok"] is False and r["rolled_back"] and r["reason"] == "build broke"
    assert script.calls == ["deploy", "rollback"] and script.rollback_args == ({}, None)


def test_health_retries_use_clock(phoenix_env, lib, adapters, script):
    make_project(phoenix_env)
    script.health_answers = [(False, "no"), (False, "no"), (True, "up")]
    r = deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert r["ok"] and script.calls.count("health") == 3
    assert adapters.clock.sleeps == [2.0, 2.0]          # timeout_s 10 / tries 5
    script.health_answers = [(False, "no")]
    adapters.clock.sleeps.clear()
    assert deploy.run_deploy(adapters, "demo", who="t", commit="c2")["rolled_back"]
    assert len(adapters.clock.sleeps) == 4


def connect_github():
    keys.write_secret_file(services.get("github")["secrets_file"], {"GH_TOKEN": "tok"})
    services.write_registry({"github": {"connected": True}})


def test_proxy_started_for_proxy_service_and_stopped(phoenix_env, lib, adapters, script, monkeypatch):
    make_project(phoenix_env, "scripted-proxy")
    connect_github()
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    r = deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert r["ok"], r["reason"]
    assert [s["service"] for s in adapters.proxy.started] == ["github"] and adapters.proxy.started[0]["bind"] == "127.0.0.1"
    assert adapters.proxy.running() == [] and adapters.proxy.stopped == ["github"]
    assert script.seen["dctx"].proxy == {"url": "http://proxy.fake/github", "token": "fake-proxy-token"}
    script.fail_deploy = "boom"
    script.deploy = lambda dctx: (_ for _ in ()).throw(RuntimeError("crash"))
    script.install()
    deploy.run_deploy(adapters, "demo", who="t", commit="c2")
    assert adapters.proxy.running() == [] and len(adapters.proxy.stopped) == 2


def test_proxy_service_not_connected_is_plain(phoenix_env, lib, adapters, script):
    make_project(phoenix_env, "scripted-proxy")
    r = deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert r["ok"] is False and "not connected" in r["reason"] and "deploy" not in script.calls


def test_env_file_0600_and_removed(phoenix_env, lib, adapters, script):
    make_project(phoenix_env)
    keys.set_key("demo", "MY_KEY", SENTINEL)
    deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert script.seen["env_mode"] == 0o600
    assert not script.seen["env_path"].exists()


def test_deploy_settings_merge_and_validation(phoenix_env, lib, adapters, script):
    folder = make_project(phoenix_env, extra='label = "mine"\n')
    deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    assert script.seen["dctx"].settings == {"live_port": 8080, "label": "mine"}
    assert settings.check(folder) == []
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "scripted"\n\n[deploy.settings]\nlive_port = 8080\nbogus = 1\n')
    assert any("unknown key 'bogus'" in p for p in settings.check(folder))
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "scripted"\n')
    assert any("'live_port' must be set" in p for p in settings.check(folder))
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "scripted"\n\n[deploy.settings]\nlive_port = "80"\n')
    assert any("live_port" in p and "whole number" in p for p in settings.check(folder))
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "nope"\n')
    assert any("'nope' is not a deployer" in p for p in settings.check(folder))
    (folder / "phoenix.toml").write_text('[deploy]\nwith = "none"\n')
    assert settings.check(folder) == []


def test_profile_suggested_deployers_exist():
    names = set(deploy.load_library(REAL / "deployers"))
    assert deploy.load_problems(REAL / "deployers") == []
    for toml in (REAL / "profiles").glob("*/profile.toml"):
        assert settings.load_profile(REAL, toml.parent.name)["suggested_deployer"] in names


def test_preview_runs_without_rollback_and_refused_when_not_supported(phoenix_env, lib, adapters, script):
    make_project(phoenix_env)
    r = deploy.run_preview(adapters, "demo", who="t", run_id="r1", commit="c1", source_dir=phoenix_env["projects"])
    assert r["ok"] and r["kind"] == "preview" and r["url"] == "https://prev.example"
    assert deploy.last_good("demo") is None
    script.health_answers = [(False, "down")]
    r = deploy.run_preview(adapters, "demo", who="t", run_id="r2", commit="c1", source_dir=phoenix_env["projects"])
    assert not r["ok"] and not r["rolled_back"] and "rollback" not in script.calls
    assert deploy.stop_preview(adapters, "demo", who="t", run_id="r1")["ok"] and "stop_preview" in script.calls


def test_cli_deploy_requires_yes(phoenix_env, lib, adapters, script, monkeypatch, capsys):
    make_project(phoenix_env)
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    assert main(["deploy", "now", "demo"]) == 1
    assert "--yes" in capsys.readouterr().err and "deploy" not in script.calls
    assert main(["deploy", "now", "demo", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert main(["deploy", "status", "demo"]) == 0
    assert "https://demo.example" in capsys.readouterr().out
    assert "deploy now demo" in (paths.logs() / "commands.jsonl").read_text()


def test_deployers_list_shows_all_six(capsys):
    assert main(["deployers", "list", "--json"]) == 0
    rows = {d["name"]: d for d in json.loads(capsys.readouterr().out)["deployers"]}
    assert set(rows) == {"none", "vps-docker", "github-release", "cloudflare-pages", "vercel", "expo-eas"}
    assert rows["none"]["supported"] is True and rows["vercel"]["supported"] is False
    assert rows["vps-docker"]["suggested_for"] == ["web"]


def test_no_secret_in_deploy_log(phoenix_env, lib, adapters, script):
    make_project(phoenix_env)
    keys.set_key("demo", "MY_KEY", SENTINEL)
    deploy.run_deploy(adapters, "demo", who="t", commit="c1")
    log = paths.logs() / "deploy-demo.log"
    assert "using key" in log.read_text() and SENTINEL not in log.read_text()
