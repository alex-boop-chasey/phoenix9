"""The rules for the phoenix9 project's own settings, and deploy/self-project.toml."""
import tomllib
from pathlib import Path

from phoenix9 import library, paths, settings

REPO = Path(__file__).resolve().parents[1]


def project(tmp_path, text, name="phoenix9"):
    folder = paths.projects() / name
    folder.mkdir(parents=True)
    (folder / "phoenix.toml").write_text(text)
    return folder


def test_self_project_merge_must_be_ask(tmp_path):
    folder = project(tmp_path, 'preset = "quick"\nmerge = "auto"\n')
    problems = settings.check(folder, library.load_library(REPO))
    assert any("phoenix9's merge mode is fixed to ask (updates spec 3.2)" in p for p in problems)
    other = project(tmp_path, 'preset = "quick"\nmerge = "auto"\n', "other")
    assert settings.check(other, library.load_library(REPO)) == []


def test_self_project_deployer_must_be_none(tmp_path):
    folder = project(tmp_path, 'preset = "quick"\nmerge = "ask"\n[deploy]\nwith = "vps-docker"\n')
    assert any("[deploy] with must be none" in p for p in settings.check(folder, library.load_library(REPO)))


def test_self_project_name_comes_from_global_toml(tmp_path):
    paths.config().mkdir(parents=True)
    (paths.config() / "global.toml").write_text('[update]\nproject = "mine"\n')
    folder = project(tmp_path, 'preset = "quick"\n', "mine")
    assert settings.check(folder, library.load_library(REPO))


def test_self_project_toml_valid_and_safety_files_exist(tmp_path):
    text = (REPO / "deploy" / "self-project.toml").read_text()
    data = tomllib.loads(text)
    lib = library.load_library(REPO)
    assert settings.validate(data, settings.all_specs(lib), "self-project.toml") == []
    assert settings.self_project_problems("phoenix9", data) == []
    assert data["merge"] == "ask" and data["deploy"]["with"] == "none" and data["profile"] == "platform"
    assert data["safety_files"] and all((REPO / f).exists() for f in data["safety_files"])
    folder = project(tmp_path, text)
    assert settings.check(folder, lib) == []
