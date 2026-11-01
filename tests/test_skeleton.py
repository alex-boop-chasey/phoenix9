"""The skeleton works: package imports, paths honour env vars, atomic writes behave."""
from pathlib import Path

from phoenix9 import __version__, atomic, paths
from phoenix9.__main__ import main


def test_version():
    assert __version__.startswith("9.")


def test_paths_follow_env(phoenix_env):
    assert paths.home() == phoenix_env["home"]
    assert paths.projects() == phoenix_env["projects"]
    assert paths.runs("p") == phoenix_env["home"] / "runs" / "p"


def test_atomic_roundtrip(tmp_path):
    f = tmp_path / "a" / "b.json"
    atomic.write_json(f, {"x": 1}, mode=0o600)
    assert atomic.read_json(f) == {"x": 1}
    assert (f.stat().st_mode & 0o777) == 0o600
    assert atomic.read_json(tmp_path / "missing.json", default=[]) == []


def test_main_runs(capsys):
    assert main([]) == 0
    assert "phoenix" in capsys.readouterr().out
