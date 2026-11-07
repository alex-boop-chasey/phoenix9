"""The rules for the phoenix9 project's own settings, and deploy/self-project.toml."""
import fnmatch
import tomllib
from pathlib import Path

from helpers.stepunit import load
from phoenix9 import library, paths, settings

REPO = Path(__file__).resolve().parents[1]


MUST_BE_FLAGGED = [
    "image/init-firewall.sh", "image/entry.sh", "image/hands-dns-conf.sh", "image/Dockerfile",
    *[f"profiles/{p}/image/Dockerfile" for p in ("desktop", "mobile", "platform", "python-script", "research", "web")],
    "phoenix9/docker.py", "phoenix9/git.py", "phoenix9/checklock.py", "steps/diff-rules/run.py",
    "steps/secret-scan/run.py", "phoenix9/scrub.py", "phoenix9/keys.py", "phoenix9/proxy.py",
    "phoenix9/stepproxy.py", "phoenix9/adapters.py", "phoenix9/runner.py", "phoenix9/stepctx.py",
    "phoenix9/updater.py", "phoenix9/hold.py", "deploy/update.sh", "deploy/phoenix9-update.service",
    "deploy/install.sh", "deploy/phoenix-api.service", "deploy/phoenix-runner.service",
    "check.sh", "check-browser.sh",
]


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
    assert data["safety_files"]
    files = [p.relative_to(REPO).as_posix() for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts]
    for glob in data["safety_files"]:
        assert any(fnmatch.fnmatch(f, glob) for f in files), f"{glob} matches no file"
    matches = load("merge").matches_safety
    for path in MUST_BE_FLAGGED:
        assert (REPO / path).is_file(), path
        assert matches(path, data["safety_files"]), f"{path} is not flagged"
    folder = project(tmp_path, text)
    assert settings.check(folder, lib) == []


def test_phoenix9_pyproject_declares_no_dependencies():
    """Phoenix installs nothing from pyproject (pytest comes from the step image and the server), so the
    lockfile step must not ask phoenix9 for a uv/poetry lockfile."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert data["project"]["dependencies"] == []
    assert "optional-dependencies" not in data["project"] and "dependency-groups" not in data
    assert load("lockfile")._has_dependencies(REPO) is False
