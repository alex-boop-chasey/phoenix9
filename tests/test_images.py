"""Tests for `phoenix images build` with the fake Docker."""
import json
import os
import subprocess

import pytest

from phoenix9 import paths
from phoenix9.__main__ import main
from phoenix9.ops import images


def git(root, *argv):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *argv], cwd=root, check=True, env=env, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def lib(tmp_path, monkeypatch, adapters):
    """A tiny library repo with two profiles and the base image, plus the fakes wired into ops."""
    root = tmp_path / "lib"
    for name in ("alpha", "beta"):
        (root / "profiles" / name / "image").mkdir(parents=True)
        (root / "profiles" / name / "profile.toml").write_text(f'image = "phoenix9-step-{name}:1"\n')
        (root / "profiles" / name / "image" / "Dockerfile").write_text("FROM scratch\n")
    (root / "image").mkdir()
    (root / "image" / "Dockerfile").write_text("FROM scratch\n")
    (root / "image" / "init-firewall.sh").write_text("#!/bin/sh\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    monkeypatch.setattr("phoenix9.ops.common.make_adapters", lambda: adapters)
    adapters.root = root
    return adapters


def built_tags(a):
    return [c[1][1] for c in a.docker.calls if c[0] == "build"]


def test_images_build_changed_only(lib, capsys):
    head = git(lib.root, "rev-parse", "HEAD")
    lib.docker.images["phoenix9-step-alpha:1"] = {"phoenix9.commit": head}
    lib.docker.images["phoenix9-step-beta:1"] = {"phoenix9.commit": head}
    assert main(["images", "build", "--profile", "alpha", "--profile", "beta", "--changed"]) == 0
    assert built_tags(lib) == [] and "unchanged" in capsys.readouterr().out
    (lib.root / "profiles" / "beta" / "image" / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    git(lib.root, "commit", "-qam", "two")
    assert main(["images", "build", "--profile", "alpha", "--profile", "beta", "--changed"]) == 0
    assert built_tags(lib) == ["phoenix9-step-beta:1"]
    new = git(lib.root, "rev-parse", "HEAD")
    assert lib.docker.images["phoenix9-step-beta:1"] == {"phoenix9.commit": new}
    (lib.root / "image" / "init-firewall.sh").write_text("#!/bin/sh\necho hi\n")   # shared scripts: all profiles
    git(lib.root, "commit", "-qam", "three")
    assert main(["images", "build", "--profile", "alpha", "--profile", "beta", "--changed"]) == 0
    assert built_tags(lib)[1:] == ["phoenix9-step-alpha:1", "phoenix9-step-beta:1"]


def test_changed_builds_a_missing_image(lib):
    assert main(["images", "build", "--profile", "alpha", "--changed"]) == 0
    assert built_tags(lib) == ["phoenix9-step-alpha:1"]


def test_build_uses_repo_root_context_and_base_only_when_asked(lib, phoenix_env):
    (phoenix_env["projects"] / "demo").mkdir()
    (phoenix_env["projects"] / "demo" / "phoenix.toml").write_text('profile = "beta"\n')
    assert main(["images", "build"]) == 0                       # default = profiles projects use
    (_, args, _), = [c for c in lib.docker.calls if c[0] == "build"]
    assert args[1] == "phoenix9-step-beta:1" and args[2] == str(lib.root)
    assert args[0] == str(lib.root / "profiles" / "beta" / "image" / "Dockerfile")
    assert main(["images", "build", "--all"]) == 0
    assert built_tags(lib)[-3:] == ["phoenix9-step-alpha:1", "phoenix9-step-beta:1", "phoenix9-step:base"]
    base = [c for c in lib.docker.calls if c[0] == "build"][-1][1]
    assert base[2] == str(lib.root / "image")


def test_images_build_failure_exit_1(lib, capsys):
    lib.docker.build_codes[:] = [1, 0]
    code = main(["images", "build", "--profile", "alpha", "--profile", "beta", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and not data["ok"]
    assert [b["ok"] for b in data["built"]] == [False, True]      # the second still built


def test_unknown_profile_is_refused(lib, capsys):
    assert main(["images", "build", "--profile", "nope"]) == 1
    assert "no profile called 'nope'" in capsys.readouterr().err
