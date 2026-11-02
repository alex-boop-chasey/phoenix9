"""Static checks on the profile Dockerfiles (no Docker is run)."""
import re
import tomllib
from pathlib import Path

import pytest

from phoenix9.images import dockerfile_problems

ROOT = Path(__file__).resolve().parent.parent
PROFILES = sorted(p.name for p in (ROOT / "profiles").iterdir() if p.is_dir())
BAD = {"latest": "pinned", "root-user": "non-root", "extra-sudoers": "sudoers",
       "unpinned-claude": "Claude Code", "token-env": "ENV"}


def test_every_profile_has_dockerfile():
    assert len(PROFILES) == 6
    for name in PROFILES:
        assert (ROOT / "profiles" / name / "image" / "Dockerfile").is_file(), name


@pytest.mark.parametrize("name", PROFILES)
def test_dockerfile_problems_empty_for_all_profiles(name):
    assert dockerfile_problems(ROOT / "profiles" / name / "image" / "Dockerfile") == []


def test_base_dockerfile_is_clean():
    assert dockerfile_problems(ROOT / "image" / "Dockerfile") == []


@pytest.mark.parametrize("sample", sorted(BAD))
def test_problems_found_in_bad_samples(sample):
    found = dockerfile_problems(ROOT / "tests" / "data" / "dockerfiles" / f"{sample}.Dockerfile")
    assert any(BAD[sample] in p for p in found), found


def _versions_env():
    pairs = re.findall(r"^(\w+)=(\S+)$", (ROOT / "image" / "versions.env").read_text(), re.MULTILINE)
    return dict(pairs)


def test_arg_defaults_match_versions_env():
    env = _versions_env()
    files = [ROOT / "image" / "Dockerfile"] + [ROOT / "profiles" / n / "image" / "Dockerfile" for n in PROFILES]
    for path in files:
        for name, value in re.findall(r"^ARG (\w+)=(\S+)$", path.read_text(), re.MULTILINE):
            if name in env:
                assert value == env[name], f"{path}: {name}"


@pytest.mark.parametrize("name", PROFILES)
def test_profile_image_names(name):
    data = tomllib.loads((ROOT / "profiles" / name / "profile.toml").read_text())
    assert re.fullmatch(r"phoenix9-step-[a-z]+:\d+", data["image"])
