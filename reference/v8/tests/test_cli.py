from phoenix import __version__
from phoenix.__main__ import main


def test_version(capsys):
    assert main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_paths_prints_and_creates(phoenix_home, capsys):
    assert main(["paths"]) == 0
    out = capsys.readouterr().out
    for name in ("home", "plans", "runs", "config", "cache"):
        assert name in out
        assert (phoenix_home / name).is_dir() or name == "home"
    assert phoenix_home.is_dir()
