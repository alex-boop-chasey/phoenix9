"""Tests for the agent settings loader."""
from pathlib import Path

import pytest

from agentkit import config

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def test_defaults():
    c = config.Config()
    assert c.phoenix_api == "http://127.0.0.1:8095"
    assert c.model == "claude-sonnet-5-5"
    assert c.pack == "phoenix" and c.port == 8097 and c.host == "127.0.0.1"
    assert c.link_schemes == ["claude"]
    assert c.api_key_file == "/var/lib/phoenix9/agentkit/api-key"
    assert not c.prices_ready()


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "none.toml") == config.Config()


def test_example_loads():
    c = config.load(EXAMPLE)
    assert c.model == "claude-sonnet-5-5"
    assert all(v == "CHECK BEFORE USE" for t in c.prices.values() for v in t.values())
    assert not c.prices_ready()


def test_prices_ready_when_numbers(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[prices.claude-sonnet-5-5]\n" + "".join(
        f"{k} = 1.5\n" for k in config.PRICE_KEYS))
    assert config.load(p).prices_ready()
    p.write_text(p.read_text().replace("cache_write_per_mtok = 1.5", 'cache_write_per_mtok = "x"'))
    assert not config.load(p).prices_ready()


def test_unknown_key_refused(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("colour = 1\n")
    with pytest.raises(config.ConfigError, match="Unknown setting 'colour'"):
        config.load(p)
