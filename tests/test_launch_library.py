"""The real launch library: steps, presets and profiles load, resolve and validate."""
from pathlib import Path

import pytest

from phoenix9 import settings
from phoenix9.library import load_library
from phoenix9.resolve import resolve

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ["web", "mobile", "desktop", "python-script", "research", "platform"]


@pytest.fixture(scope="module")
def lib():
    return load_library(ROOT)


def plan_for(lib, tmp_path, preset):
    proj = tmp_path / f"proj-{preset}"
    proj.mkdir()
    (proj / "phoenix.toml").write_text(f'preset = "{preset}"\n')
    eff = settings.effective(proj, lib)
    return resolve(lib, settings.enabled_map(eff)), eff


SIMPLE = {
    "run-start": ["pick-up", "spec-check", "branch", "service-setup"],
    "task": ["builder", "diff-rules", "secret-scan", "acceptance", "commit"],
    "run-finish": ["lockfile", "full-suite", "summary", "preview", "merge", "deploy", "notify"],
}


def test_real_library_has_no_problems(lib):
    assert lib.problems == []
    assert len(lib.steps) == 21


def test_every_step_has_a_readme(lib):
    for step in lib.steps:
        assert (step.folder / "README.md").read_text().strip()


def test_simple_preset(lib, tmp_path):
    plan, _ = plan_for(lib, tmp_path, "simple")
    assert plan.groups == SIMPLE
    assert plan.sources["builder"]["plan"] == "fallback:spec-as-written"
    assert plan.sources["commit"]["verdict"] == "fallback:pass-if-checks-passed"
    assert "red-check" in plan.off


def test_quick_preset(lib, tmp_path):
    plan, _ = plan_for(lib, tmp_path, "quick")
    expected = {**SIMPLE, "task": ["builder", "diff-rules", "secret-scan", "acceptance", "verify", "commit"]}
    assert plan.groups == expected


def test_full_preset(lib, tmp_path):
    plan, eff = plan_for(lib, tmp_path, "full")
    assert sorted(n for g in plan.groups.values() for n in g) == sorted(s.name for s in lib.steps)
    assert eff.get("steps.verify.scope") == "affected"
    assert plan.sources["builder"]["plan"] == "step:planner"
    assert plan.sources["commit"]["verdict"] == "step:reviewer"


@pytest.mark.parametrize("preset", ["simple", "quick"])
def test_red_check_off_when_check_writer_off(lib, tmp_path, preset):
    plan, _ = plan_for(lib, tmp_path, preset)
    assert not plan.is_on("check-writer") and not plan.is_on("red-check")


LIMITS = {"planner": (40, 20), "check-writer": (40, 20), "builder": (80, 45), "reviewer": (30, 15)}


def test_ai_defaults(lib):
    for step in lib.steps:
        if step.kind != "ai":
            continue
        assert step.ai["fallback_models"] == ["claude-opus-5-5"]
        assert (step.ai["max_turns"], step.ai["timeout"]) == LIMITS[step.name]
        assert step.ai["advisor"] == {"on": False, "model": "claude-opus-5-5",
                                      "when": ["blocked"], "instructions": ""}
    assert lib.step("builder").ai["model"] == "claude-fable-5-1"
    assert lib.step("reviewer").ai["model"] == "claude-sonnet-5-5"


@pytest.mark.parametrize("name", PROFILES)
def test_profile_loads_and_validates(lib, name):
    assert settings.check_profile(ROOT, name, lib) == []


def test_python_script_profile():
    data = settings.load_profile(ROOT, "python-script")
    assert data["test"]["cmd"] == "python3 -m pytest -q"
    assert data["test"]["report"] == "pytest-junit"
    assert data["image"] == "phoenix9-step-python:1"


def test_bad_profile_reported(tmp_path):
    folder = tmp_path / "profiles" / "bad"
    folder.mkdir(parents=True)
    (folder / "profile.toml").write_text('image = "x"\n[test]\nreport = "nope"\n')
    problems = settings.check_profile(tmp_path, "bad", load_library(ROOT))
    assert any("nope" in p for p in problems) and any("test.cmd" in p for p in problems)
