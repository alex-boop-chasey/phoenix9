"""`phoenix update` commands and the update facts in /api/info, on a temp install and fake host."""
import json

import pytest

from phoenix9 import atomic, paths, updater
from phoenix9.__main__ import main
from phoenix9.ops import app, common
from test_updater import layout  # noqa: F401  (fixture: origin + temp install at v9.0)


@pytest.fixture
def cli(layout, adapters, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_status_plain_and_json(cli, capsys):
    code, out, _ = run(capsys, "update", "status", "--refresh")
    assert code == 0 and "Installed v9.0." in out and "Newest v9.2: update available." in out and "Harness idle." in out
    code, out, _ = run(capsys, "update", "status", "--json")
    data = json.loads(out)
    assert data["installed"]["tag"] == "v9.0" and data["newest"] == "v9.2" and data["update_available"]


def test_status_without_install(adapters, monkeypatch, capsys):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    code, out, _ = run(capsys, "update", "status")
    assert code == 0 and "Phoenix 9 is not installed yet" in out


def test_install_requires_yes(cli, capsys):
    code, _, err = run(capsys, "update", "install", "v9.1")
    assert code == 1 and "--yes" in err
    assert not (paths.home() / "update" / "request.json").exists()


def test_install_defaults_to_newest_tag(cli, capsys):
    run(capsys, "update", "status", "--refresh")
    code, out, _ = run(capsys, "update", "install", "--yes")
    assert code == 0 and "v9.2" in out
    assert atomic.read_json(paths.home() / "update" / "request.json")["tag"] == "v9.2"


def test_install_writes_request_and_starts_unit(cli, capsys):
    code, _, _ = run(capsys, "update", "install", "v9.1", "--yes", "--who", "alex")
    req = atomic.read_json(paths.home() / "update" / "request.json")
    assert code == 0 and req["action"] == "install" and req["tag"] == "v9.1" and req["who"] == "alex"
    assert ["systemctl", "start", "--no-block", "phoenix9-update.service"] in cli.host.calls
    assert "update install v9.1" in (paths.logs() / "commands.jsonl").read_text()


def test_info_update_reports_tags(cli):
    updater.status(cli, refresh=True)
    upd = app.info()["update"]
    assert upd["supported"] is True and upd["installed"] == "v9.0" and upd["newest"] == "v9.2"
    assert upd["available"] and upd["can_install"]


def test_rollback_requires_yes(cli, capsys):
    code, _, err = run(capsys, "update", "rollback")
    assert code == 1 and "--yes" in err
    assert not (paths.home() / "update" / "request.json").exists()


def test_wait_polls_until_done(cli, capsys, monkeypatch):
    answers = iter([False, True, True, False])  # install's own check, then two polls busy, then done
    real = updater.status

    def fake_status(adapters, refresh=False):
        st = real(adapters, refresh=refresh)
        return {**st, "running": next(answers, False),
                "last": {"action": "install", "tag": "v9.1", "result": "installed", "reason": ""}}
    monkeypatch.setattr(updater, "status", fake_status)
    code, out, _ = run(capsys, "update", "install", "v9.1", "--yes", "--wait")
    assert code == 0 and "install v9.1: installed" in out
    assert cli.clock.sleeps.count(5) == 2


def test_wait_exits_1_on_failure(cli, capsys, monkeypatch):
    real = updater.status
    monkeypatch.setattr(updater, "status", lambda a, refresh=False: {
        **real(a, refresh=refresh), "running": False,
        "last": {"action": "install", "tag": "v9.1", "result": "tests-failed", "reason": "x"}})
    code, out, _ = run(capsys, "update", "install", "v9.1", "--yes", "--wait")
    assert code == 1 and "tests-failed" in out


def test_log_shows_tail(cli, capsys):
    run(capsys, "update", "install", "v9.1", "--yes")
    code, out, _ = run(capsys, "update", "log", "--lines", "5")
    assert code == 0 and "asked for install v9.1" in out


def test_status_says_when_install_is_off_a_release(cli, layout, capsys):
    from test_updater import git
    (layout["install"] / "local.txt").write_text("hand change\n")
    git(layout["install"], "add", "-A")
    git(layout["install"], "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "by hand")
    sha = git(layout["install"], "rev-parse", "HEAD").strip()
    code, out, _ = run(capsys, "update", "status")
    assert code == 0
    assert (f"Installed copy is on commit {sha[:10]}, not a release. "
            "Run `phoenix update release` then `phoenix update install`.") in out
    data = json.loads(run(capsys, "update", "status", "--json")[1])
    assert data["off_release"] is True and "not a release" in data["off_release_note"]


def test_status_on_a_release_has_no_off_release_note(cli, capsys):
    data = json.loads(run(capsys, "update", "status", "--json")[1])
    assert data["off_release"] is False and data["off_release_note"] == ""
