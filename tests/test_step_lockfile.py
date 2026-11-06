"""The Lockfile check step: a package list needs a lockfile committed in git (real step, temp git repo)."""
import pytest

from helpers.stepunit import git, load, make_ctx, make_work, write
from helpers.stepunit import REPO
from phoenix9 import settings
from phoenix9.library import load_library

mod = load("lockfile")
PYPROJECT = '[project]\nname = "x"\nversion = "1"\ndependencies = ["requests==2.0"]\n'


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def check(tmp_path, adapters, work, files, commit=True, profile=None):
    write(work, files)
    if commit and files:
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "files")
    ctx = make_ctx(tmp_path, adapters, work, "lockfile")
    ctx.project.profile.update(profile or {})
    return mod.run(ctx)


def test_nothing_to_check_passes(tmp_path, adapters, work):
    assert check(tmp_path, adapters, work, {"a.py": "x = 1\n"}).status == "pass"


@pytest.mark.parametrize("lock", ["pnpm-lock.yaml", "package-lock.json", "yarn.lock"])
def test_package_json_with_lockfile_passes(tmp_path, adapters, work, lock):
    assert check(tmp_path, adapters, work, {"package.json": "{}", lock: "x"}).status == "pass"


def test_package_json_without_lockfile_fails_naming_it(tmp_path, adapters, work):
    result = check(tmp_path, adapters, work, {"package.json": "{}"})
    assert result.status == "fail" and "package.json has no committed lockfile" in result.reasons[0]
    assert "pnpm-lock.yaml" in result.reasons[0]


def test_lockfile_on_disk_but_not_committed_fails(tmp_path, adapters, work):
    write(work, {"package.json": "{}"})
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "pkg")
    result = check(tmp_path, adapters, work, {"pnpm-lock.yaml": "x"}, commit=False)
    assert result.status == "fail"


def test_cargo(tmp_path, adapters, work):
    assert check(tmp_path, adapters, work, {"Cargo.toml": "[package]\n"}).status == "fail"
    assert check(tmp_path, adapters, work, {"Cargo.lock": "x"}).status == "pass"


def test_pyproject_with_dependencies_needs_lock(tmp_path, adapters, work):
    result = check(tmp_path, adapters, work, {"pyproject.toml": PYPROJECT})
    assert result.status == "fail" and "uv.lock or poetry.lock" in result.reasons[0]
    assert check(tmp_path, adapters, work, {"poetry.lock": "x"}).status == "pass"


def test_pyproject_without_dependencies_passes(tmp_path, adapters, work):
    text = '[project]\nname = "x"\nversion = "1"\n[tool.poetry.dependencies]\npython = "^3.12"\n'
    assert check(tmp_path, adapters, work, {"pyproject.toml": text}).status == "pass"


def test_profile_lockfiles_override(tmp_path, adapters, work):
    files = {"package.json": "{}", "bun.lockb": "x"}
    assert check(tmp_path, adapters, work, files, profile={"lockfiles": ["bun.lockb"]}).status == "pass"
    assert check(tmp_path, adapters, work, {}, profile={"lockfiles": ["other.lock"]}).status == "fail"


def test_profile_lockfiles_is_checked(tmp_path):
    lib = tmp_path / "lib"
    (lib / "profiles" / "p").mkdir(parents=True)
    (lib / "profiles" / "p" / "profile.toml").write_text(
        'image = "i"\nlockfiles = "bun.lockb"\n[test]\ncmd = "x"\n')
    problems = settings.check_profile(lib, "p", load_library(REPO))
    assert any("lockfiles" in p for p in problems)
