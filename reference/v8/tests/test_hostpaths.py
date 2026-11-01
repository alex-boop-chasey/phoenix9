"""Tests for phoenix/hostpaths.py: mapping Phoenix's paths to Docker host paths."""
import json
import subprocess
from pathlib import Path

import pytest

from phoenix import checks, config, docker, hostpaths

VOLUMES = "plans=phoenix-plans,runs=phoenix-runs,config=phoenix-config,cache=phoenix-cache"


def fake_inspect(volume):
    return f"/var/lib/docker/volumes/{volume}/_data"


@pytest.fixture
def mapped(monkeypatch):
    """Switch the mapping on with fake volume mountpoints."""
    monkeypatch.setenv("PHOENIX_VOLUMES", VOLUMES)
    config.paths().create()
    hostpaths.load(inspect=fake_inspect)
    return config.paths()


def test_off_without_the_setting(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("x")
    assert not hostpaths.enabled()
    assert hostpaths.load(inspect=fake_inspect) == []
    assert hostpaths.to_host(f) == f.resolve()


def test_parse_volumes():
    assert hostpaths.parse_volumes(VOLUMES) == {"plans": "phoenix-plans", "runs": "phoenix-runs",
                                                "config": "phoenix-config", "cache": "phoenix-cache"}
    with pytest.raises(hostpaths.HostPathError, match="bad item"):
        hostpaths.parse_volumes("plans=phoenix-plans,home=x")
    with pytest.raises(hostpaths.HostPathError, match="bad item"):
        hostpaths.parse_volumes("plans")


def test_every_folder_must_be_named(monkeypatch):
    monkeypatch.setenv("PHOENIX_VOLUMES", "plans=phoenix-plans,runs=phoenix-runs")
    with pytest.raises(hostpaths.HostPathError, match="config, cache"):
        hostpaths.load(inspect=fake_inspect)


def test_paths_in_volumes_are_mapped(mapped):
    runs_file = mapped.runs / "abcd" / "prompts" / "1-1-builder.md"
    assert hostpaths.to_host(runs_file) == Path("/var/lib/docker/volumes/phoenix-runs/_data/abcd/prompts/1-1-builder.md")
    assert hostpaths.to_host(mapped.cache) == Path("/var/lib/docker/volumes/phoenix-cache/_data")
    assert hostpaths.to_host(mapped.config / "projects" / "a.domains") == \
        Path("/var/lib/docker/volumes/phoenix-config/_data/projects/a.domains")


def test_paths_outside_volumes_are_refused(mapped):
    with pytest.raises(hostpaths.HostPathError, match="not inside a Phoenix volume"):
        hostpaths.to_host(Path("/etc/passwd"))


def test_assets_are_copied_into_the_cache_and_mapped(mapped):
    tag = hostpaths.tree_hash(checks.TESTCONFIG_DIR)
    copy = mapped.cache / "assets" / tag / checks.TESTCONFIG_DIR.resolve().relative_to("/")
    assert (copy / "vitest.config.mjs").read_text() == (checks.TESTCONFIG_DIR / "vitest.config.mjs").read_text()
    expected = Path("/var/lib/docker/volumes/phoenix-cache/_data/assets") / tag / checks.TESTCONFIG_DIR.resolve().relative_to("/")
    assert hostpaths.to_host(checks.TESTCONFIG_DIR / "vitest.config.mjs") == expected / "vitest.config.mjs"
    assert hostpaths.to_host(docker.HOOKS_DIR).parts[:6] == ("/", "var", "lib", "docker", "volumes", "phoenix-cache")


def test_an_existing_asset_copy_is_never_changed(mapped):
    tag = hostpaths.tree_hash(checks.TESTCONFIG_DIR)
    copy = mapped.cache / "assets" / tag / checks.TESTCONFIG_DIR.resolve().relative_to("/")
    marker = copy / "in-use.txt"
    marker.write_text("a running container has this folder mounted")
    hostpaths.load(inspect=fake_inspect)            # a second command starting (e.g. doctor)
    assert marker.read_text().startswith("a running")


def test_tree_hash_follows_the_contents(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("one")
    first = hostpaths.tree_hash(tmp_path / "a")
    (tmp_path / "a" / "x.txt").write_text("two")
    assert hostpaths.tree_hash(tmp_path / "a") != first


def test_mount_arg_uses_the_host_path(mapped):
    f = mapped.runs / "abcd" / "prompt.md"
    f.parent.mkdir(parents=True)
    f.write_text("hi")
    arg = docker.Mount(f, "/phoenix/prompt.md").arg()
    assert arg == "type=bind,src=/var/lib/docker/volumes/phoenix-runs/_data/abcd/prompt.md,dst=/phoenix/prompt.md,readonly"
    assert docker.Mount("some-volume", "/pnpm-store", ro=False).arg() == "type=volume,src=some-volume,dst=/pnpm-store"


def test_mount_arg_still_needs_the_file_inside(mapped):
    with pytest.raises(FileNotFoundError):
        docker.Mount(mapped.runs / "missing.md", "/x").arg()


def test_check_container_argv_has_only_host_paths(mapped):
    checkout = mapped.cache / "work" / "r-1-1"
    out = mapped.runs / "r" / "3-product" / "reports" / "1-1"
    checkout.mkdir(parents=True)
    out.mkdir(parents=True)
    r = docker.check_run("r", 1, 1, "verify", checkout, "true", None, None, "store",
                         extra_mounts=checks.check_mounts(out))
    argv = docker.build_argv(r, config.DEFAULTS)
    binds = [a for a in argv if a.startswith("type=bind")]
    assert len(binds) == 3
    assert all("src=/var/lib/docker/volumes/" in b for b in binds)


def test_docker_volume_mountpoint_reads_docker(monkeypatch):
    def fake_run(argv, **kw):
        assert argv == ["docker", "volume", "inspect", "phoenix-runs"]
        return subprocess.CompletedProcess(argv, 0, json.dumps([{"Mountpoint": "/v/runs/_data"}]), "")
    monkeypatch.setattr(hostpaths.subprocess, "run", fake_run)
    assert hostpaths.docker_volume_mountpoint("phoenix-runs") == "/v/runs/_data"


def test_docker_volume_mountpoint_missing_volume(monkeypatch):
    monkeypatch.setattr(hostpaths.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "[]", "Error: no such volume"))
    with pytest.raises(hostpaths.HostPathError, match="no such volume"):
        hostpaths.docker_volume_mountpoint("phoenix-runs")


def test_watch_stops_when_the_volumes_cannot_be_found(monkeypatch, capsys):
    from phoenix.__main__ import main

    def broken(volume):
        raise hostpaths.HostPathError(f"docker volume inspect {volume} failed: no such volume")
    monkeypatch.setenv("PHOENIX_VOLUMES", VOLUMES)
    monkeypatch.setattr(hostpaths, "docker_volume_mountpoint", broken)
    assert main(["watch"]) == 1
    assert "cannot find Phoenix's volumes" in capsys.readouterr().out


def test_deploy_files_exist_and_say_the_right_things():
    root = Path(__file__).resolve().parent.parent / "deploy"
    compose = (root / "docker-compose.yml").read_text()
    for needle in ("python -m phoenix watch", "unless-stopped", "/var/run/docker.sock",
                   "phoenix-plans:/phoenix/plans", "phoenix-runs:/phoenix/runs",
                   "phoenix-config:/phoenix/config", "phoenix-cache:/phoenix/cache",
                   "PHOENIX_HOME: /phoenix", "mem_limit: 1g", "PHOENIX_VOLUMES"):
        assert needle in compose, needle
    dockerfile = (root / "Dockerfile.phoenix").read_text()
    assert "python:3.12-slim" in dockerfile
    for banned in ("nodejs", "npm ", "claude-code", "@anthropic-ai"):
        assert banned not in dockerfile.lower(), banned
    install = (root / "install.sh").read_text()
    assert "read -rs" in install and "chmod 600" in install and "phoenix doctor" in install


def test_root_compose_file_only_includes_the_deploy_one():
    root = Path(__file__).resolve().parent.parent
    text = (root / "docker-compose.yml").read_text()
    assert "path: deploy/docker-compose.yml" in text and "env_file: deploy/.env" in text
    assert "services:" not in text
