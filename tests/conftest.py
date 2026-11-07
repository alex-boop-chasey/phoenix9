"""Shared test fixtures: every test gets its own temp Phoenix home and projects folder."""
import pytest


@pytest.fixture(autouse=True)
def phoenix_env(tmp_path, monkeypatch):
    """Point PHOENIX_HOME and PHOENIX_PROJECTS at temp folders so no test touches the real server."""
    home = tmp_path / "phoenix-home"
    projects = tmp_path / "projects"
    home.mkdir()
    projects.mkdir()
    monkeypatch.setenv("PHOENIX_HOME", str(home))
    monkeypatch.setenv("PHOENIX_PROJECTS", str(projects))
    monkeypatch.setenv("PHOENIX_INSTALL", str(tmp_path / "install"))
    monkeypatch.setenv("PHOENIX_NOTIFY_FILE", str(tmp_path / "notify.msg"))
    monkeypatch.setenv("PHOENIX_SYSTEMD_DIR", str(tmp_path / "systemd"))
    return {"home": home, "projects": projects}


@pytest.fixture
def adapters(tmp_path):
    """The fake adapter set (fake host, clock, notify, http, docker, claude, chat)."""
    from fakes import fake_adapters
    return fake_adapters(tmp_path)
