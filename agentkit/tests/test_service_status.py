"""Checks the service's front door: token, /status, never root, and the key staying private."""
import logging
import os

import pytest
from starlette.testclient import TestClient

from agentkit import config, service

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_client(tmp_path, with_key: bool, key: str):
    """Build the app from a config whose key file is present or missing."""
    (tmp_path / "token").write_text(TOKEN)
    key_file = tmp_path / "api-key"
    if with_key:
        key_file.write_text(key + "\n")
    cfg = config.Config(token_file=str(tmp_path / "token"), api_key_file=str(key_file),
                        db_file=str(tmp_path / "agent.db"))
    return TestClient(service.app_from_config(cfg))


@pytest.fixture
def key_value():
    """A made-up key value, built at run time (never a real key)."""
    return "not-a-real-key-" + os.urandom(8).hex()


def test_no_token_or_wrong_token_is_401(tmp_path, key_value):
    client = make_client(tmp_path, True, key_value)
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/threads/x/stream").status_code == 401


def test_refuses_to_start_as_root(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(os, "getuid", lambda: 0)
    assert service.main(["--config", str(tmp_path / "config.toml")]) == 1
    assert "won't run as root" in capsys.readouterr().err


@pytest.mark.parametrize("present", [True, False])
def test_key_present_flag_and_key_never_leaks(tmp_path, caplog, key_value, present):
    caplog.set_level(logging.DEBUG)
    client = make_client(tmp_path, present, key_value)
    reply = client.get("/status", headers=AUTH)
    assert reply.status_code == 200
    body = reply.json()
    assert body == {"running": True, "key_present": present, "pack": "phoenix", "model": "claude-sonnet-5-5"}
    assert key_value not in reply.text
    assert key_value not in caplog.text
    assert all(key_value not in v for v in os.environ.values())
