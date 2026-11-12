"""Tests for the daily report settings: defaults, odd values, refused saves and the not-a-safety-key rule."""
import pytest

from phoenix9 import paths, settings
from phoenix9.ops import settings as ops_settings

DEFAULTS = {"enabled": True, "time": "08:00", "timezone": "Australia/Melbourne"}


def _global(tmp_path, monkeypatch, text):
    monkeypatch.setenv("PHOENIX_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "global.toml").write_text(text)


def test_defaults(tmp_path, monkeypatch):
    _global(tmp_path, monkeypatch, "")
    assert settings.report_settings() == DEFAULTS


def test_overrides(tmp_path, monkeypatch):
    _global(tmp_path, monkeypatch, '[report]\nenabled = false\ntime = "17:45"\ntimezone = "UTC"\n')
    assert settings.report_settings() == {"enabled": False, "time": "17:45", "timezone": "UTC"}


@pytest.mark.parametrize("body", ['enabled = "yes"\ntime = "8am"\ntimezone = "Mars/Base"',
                                  'time = "24:00"\ntimezone = 5', 'time = "08:60"', 'timezone = ""'])
def test_odd_values_fall_back(tmp_path, monkeypatch, body):
    _global(tmp_path, monkeypatch, "[report]\n" + body + "\n")
    assert settings.report_settings() == DEFAULTS


def test_report_not_a_table_falls_back(tmp_path, monkeypatch):
    _global(tmp_path, monkeypatch, 'report = "oops"\n')
    assert settings.report_settings() == DEFAULTS


def test_save_keeps_other_settings(tmp_path, monkeypatch):
    _global(tmp_path, monkeypatch, 'suggestions = "off"\n[chat]\noff_after_days = 7\n')
    got = settings.save_report_settings({"time": "06:30", "timezone": "Europe/London"})
    assert got == {"enabled": True, "time": "06:30", "timezone": "Europe/London"}
    assert settings.suggestion_mode() == "off" and settings.chat_settings()["off_after_days"] == 7


@pytest.mark.parametrize("key,value", [("time", "25:00"), ("time", "8:00"), ("timezone", "Nowhere/Land"),
                                       ("enabled", "true"), ("colour", "red")])
def test_bad_save_refused_naming_setting(tmp_path, monkeypatch, key, value):
    _global(tmp_path, monkeypatch, "")
    with pytest.raises(ValueError, match=f"report.{key}"):
        settings.save_report_settings({key: value})
    assert "report" not in settings.read_global()


@pytest.mark.parametrize("key", ["report.enabled", "report.time", "report.timezone"])
def test_not_safety_keys(key):
    assert not ops_settings.is_safety_key(key)
