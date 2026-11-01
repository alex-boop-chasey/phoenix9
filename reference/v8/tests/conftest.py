"""Shared test setup: every test gets its own PHOENIX_HOME."""
import pytest


@pytest.fixture(autouse=True)
def phoenix_home(tmp_path, monkeypatch):
    """Point PHOENIX_HOME at a fresh temporary folder."""
    home = tmp_path / "home"
    monkeypatch.setenv("PHOENIX_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def no_host_path_mapping(monkeypatch):
    """Tests run as on a plain machine: no PHOENIX_VOLUMES, no mapping left over."""
    from phoenix import hostpaths
    monkeypatch.delenv("PHOENIX_VOLUMES", raising=False)
    hostpaths.reset()
    yield
    hostpaths.reset()
