import pytest

from phoenix import config


def write_toml(home, text):
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "phoenix.toml").write_text(text)


def test_defaults_when_no_toml(phoenix_home):
    assert config.load() == config.DEFAULTS
    assert config.load()["max_tries"] == 3
    assert config.load()["image"] == "phoenix-step:0.6.0"


def test_toml_overrides_defaults(phoenix_home):
    write_toml(phoenix_home, 'max_tries = 5\ncontainer_cpus = 2\nimage = "x:1"\n')
    s = config.load()
    assert s["max_tries"] == 5
    assert s["container_cpus"] == 2.0
    assert s["image"] == "x:1"
    assert s["builder_timeout_min"] == 90


def test_unknown_key_gives_readable_error(phoenix_home):
    write_toml(phoenix_home, "max_trys = 5\n")
    with pytest.raises(config.ConfigError) as e:
        config.load()
    msg = str(e.value)
    assert "'max_trys'" in msg
    assert "does not know" in msg
    assert "max_tries" in msg


def test_wrong_type_gives_readable_error(phoenix_home):
    write_toml(phoenix_home, 'max_tries = "three"\n')
    with pytest.raises(config.ConfigError, match="whole number"):
        config.load()


def test_broken_toml_gives_readable_error(phoenix_home):
    write_toml(phoenix_home, "max_tries = = 3\n")
    with pytest.raises(config.ConfigError, match="not valid TOML"):
        config.load()


def test_paths_follow_phoenix_home(phoenix_home):
    p = config.paths()
    assert p.home == phoenix_home.resolve()
    assert p.runs == phoenix_home.resolve() / "runs"
    p.create()
    for path in p.all().values():
        assert path.is_dir()
