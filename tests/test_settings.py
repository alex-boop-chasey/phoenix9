"""Settings layering: phoenix.toml checks, presets, profiles, provenance, set_value, apply_preset."""
from pathlib import Path

import pytest

from phoenix9 import settings
from phoenix9.library import load_library
from phoenix9.settings import SettingsError

DATA = Path(__file__).parent / "data" / "library"


@pytest.fixture
def lib():
    return load_library(DATA)


@pytest.fixture
def proj(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    return folder


def write(proj, text):
    (proj / "phoenix.toml").write_text(text)


def test_missing_file_works(proj, lib):
    assert settings.load_project(proj) == {}
    assert settings.check(proj, lib) == []
    eff = settings.effective(proj, lib)
    assert eff.get("max_tries") == 3 and eff.source["max_tries"] == "library"
    assert eff.get("steps.builder.on") is True
    assert eff.get("steps.planner.on") is True and eff.source["steps.planner.on"] == "preset:quick"


def test_unknown_top_level_key(proj, lib):
    write(proj, 'bogus = 1\n')
    assert any("unknown key 'bogus'" in p for p in settings.check(proj, lib))


def test_unknown_step_key_and_step_name(proj, lib):
    write(proj, '[steps.builder]\nmodle = "x"\n[steps.nothing]\non = true\n')
    problems = settings.check(proj, lib)
    assert any("steps.builder.modle" in p for p in problems)
    assert any("steps.nothing.on" in p for p in problems)


def test_ai_keys_only_on_ai_steps(proj, lib):
    write(proj, '[steps.commit]\nmodel = "x"\n[steps.builder]\nmax_turns = 5\n[steps.builder.advisor]\non = true\n')
    problems = settings.check(proj, lib)
    assert len(problems) == 1 and "steps.commit.model" in problems[0]


def test_wrong_type_and_bad_choice(proj, lib):
    write(proj, 'max_tries = "three"\nmerge = "sometimes"\n[steps.builder]\nmax_tries = true\n')
    problems = settings.check(proj, lib)
    assert any("'max_tries' must be a whole number" in p for p in problems)
    assert any("'merge'" in p and "one of" in p for p in problems)
    assert any("steps.builder.max_tries" in p for p in problems)


def test_all_problems_at_once(proj, lib):
    write(proj, 'bogus = 1\nmax_tries = "x"\non_failure = "explode"\n[steps.builder]\nzzz = 1\n')
    assert len(settings.check(proj, lib)) == 4


def test_broken_toml_is_a_problem(proj, lib):
    write(proj, 'max_tries = \n')
    problems = settings.check(proj, lib)
    assert len(problems) == 1 and "not valid TOML" in problems[0]


def test_layering_order_and_provenance(proj, lib):
    write(proj, 'profile = "py"\npreset = "quick"\n')
    eff = settings.effective(proj, lib)
    # profile beats library, preset beats profile
    assert eff.get("steps.builder.model") == "preset-quick-model"
    assert eff.source["steps.builder.model"] == "preset:quick"
    assert eff.source["merge"] == "preset:quick"
    # preset also beats profile for max_tries
    assert eff.get("steps.builder.max_tries") == 4
    # library default still shows where nothing else spoke
    assert eff.source["steps.builder.timeout"] == "library"
    # project beats preset
    write(proj, 'profile = "py"\npreset = "quick"\nmerge = "auto"\n[steps.builder]\nmodel = "mine"\n')
    eff = settings.effective(proj, lib)
    assert eff.get("steps.builder.model") == "mine" and eff.source["steps.builder.model"] == "project"
    assert eff.get("merge") == "auto" and eff.source["merge"] == "project"


def test_profile_layer_alone_and_below_preset(proj, lib):
    write(proj, 'profile = "py"\npreset = "full"\n')
    eff = settings.effective(proj, lib)
    assert eff.get("steps.builder.model") == "profile-model"
    assert eff.source["steps.builder.model"] == "profile:py"
    assert eff.get("steps.builder.max_tries") == 2
    assert eff.source["steps.check-writer.on"] == "preset:full"
    assert eff.get("on_failure") == "continue"


def test_run_overrides_win(proj, lib):
    write(proj, 'preset = "quick"\n[steps.builder]\nmodel = "mine"\n')
    eff = settings.effective(proj, lib, {"merge": "auto", "steps": {"builder": {"model": "wizard"}}})
    assert eff.get("steps.builder.model") == "wizard"
    assert eff.source["steps.builder.model"] == "run"
    assert eff.source["merge"] == "run"


def test_bad_run_overrides_refused(proj, lib):
    with pytest.raises(SettingsError, match="unknown key 'nope'"):
        settings.effective(proj, lib, {"nope": 1})


def test_missing_preset_or_profile_is_error(proj, lib):
    write(proj, 'profile = "ghost"\n')
    with pytest.raises(SettingsError, match="ghost"):
        settings.effective(proj, lib)
    write(proj, 'preset = "simple"\n')
    assert settings.effective(proj, lib).source["preset"] == "project"


def test_custom_with_based_on(proj, lib):
    write(proj, 'preset = "custom"\nbased_on = "full"\n')
    eff = settings.effective(proj, lib)
    assert eff.get("on_failure") == "continue"
    assert eff.source["on_failure"] == "preset:full"
    write(proj, 'preset = "custom"\n')  # based_on defaults to quick
    assert settings.effective(proj, lib).source["merge"] == "preset:quick"
    assert settings.load_preset(DATA, "custom") == {}


def test_load_preset_and_profile(lib):
    assert settings.load_preset(DATA, "full")["on_failure"] == "continue"
    assert "title" not in settings.load_preset(DATA, "full")
    assert settings.load_profile(DATA, "py")["image"] == "phoenix9-step-python"
    with pytest.raises(SettingsError):
        settings.load_preset(DATA, "../x")


def test_enabled_map_and_explain(proj, lib):
    write(proj, 'preset = "full"\n[steps.builder]\nmodel = "mine"\n')
    eff = settings.effective(proj, lib)
    enabled = settings.enabled_map(eff)
    assert enabled["check-writer"] is True and enabled["planner"] is False
    assert enabled["builder"] is True
    text = settings.explain(proj, lib)
    assert "Run start:" in text
    assert "steps.builder.model = 'mine'  (from project)" in text
    assert "on_failure = 'continue'  (from preset:full)" in text


def test_set_value_coercion(proj, lib):
    settings.set_value(proj, "steps.builder.model", "claude-opus-5-5", lib)
    settings.set_value(proj, "max_tries", "5", lib)
    settings.set_value(proj, "deploy.preview", "yes", lib)
    settings.set_value(proj, "services", "supabase, resend", lib)
    settings.set_value(proj, "steps.builder.advisor.when", "blocked,on-demand", lib)
    data = settings.load_project(proj)
    assert data["steps"]["builder"]["model"] == "claude-opus-5-5"
    assert data["max_tries"] == 5
    assert data["deploy"]["preview"] is True
    assert data["services"] == ["supabase", "resend"]
    assert data["steps"]["builder"]["advisor"]["when"] == ["blocked", "on-demand"]
    assert settings.check(proj, lib) == []
    settings.set_value(proj, "services", "", lib)
    assert settings.load_project(proj)["services"] == []


def test_set_value_refusals(proj, lib):
    for key, raw in [("nope", "1"), ("steps.builder.zzz", "1"), ("steps.commit.model", "x"),
                     ("max_tries", "many"), ("deploy.preview", "maybe"), ("merge", "never"),
                     ("steps.builder.advisor.when", "sometimes")]:
        with pytest.raises(SettingsError):
            settings.set_value(proj, key, raw, lib)
    assert not (proj / "phoenix.toml").exists()


def test_saved_key_order(proj, lib):
    settings.set_value(proj, "deploy.mode", "button", lib)
    settings.set_value(proj, "merge", "ask", lib)
    settings.set_value(proj, "preset", "full", lib)
    text = (proj / "phoenix.toml").read_text()
    assert text.index("preset") < text.index("merge") < text.index("[deploy]")


def test_apply_preset_keeps_settings_drops_on(proj, lib):
    write(proj, 'preset = "quick"\n[steps.builder]\nmodel = "mine"\non = true\n'
                '[steps.check-writer]\non = true\n')
    settings.apply_preset(proj, "full", lib)
    data = settings.load_project(proj)
    assert data["preset"] == "full"
    assert data["steps"]["builder"] == {"model": "mine"}
    assert "check-writer" not in data["steps"]
    with pytest.raises(SettingsError):
        settings.apply_preset(proj, "mystery", lib)
