"""The github-release deployer: tags, build in a check container, uploads, rollback, allowed calls, secrets."""
import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from phoenix9 import deploy, keys, proxy, services
from phoenix9.deploy import DeployError

REAL = Path(__file__).resolve().parent.parent
SENTINEL = "SENTINEL-GH-TOKEN-5521"
BASE = "http://proxy.fake/github"
API = BASE + "/repos/o/demo"
SHA = "a" * 40


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A temp library with the real deployers."""
    root = tmp_path / "lib"
    root.mkdir()
    for name in ("steps", "presets", "profiles", "services", "templates", "deployers"):
        (root / name).symlink_to(REAL / name)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    return root


def make_project(phoenix_env, settings_text="", build="none"):
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / ".phoenix").mkdir()
    (folder / ".phoenix" / "project.json").write_text(json.dumps({"repo": "o/demo", "profile": "python-script"}))
    code = folder / "code"
    code.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x"}
    (code / "pyproject.toml").write_text("[project]\nname='demo'\n")
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "first"]):
        subprocess.run(["git", *cmd], cwd=code, check=True, env=env, capture_output=True)
    (folder / "phoenix.toml").write_text(
        f'[deploy]\nwith = "github-release"\nmode = "button"\n\n[deploy.settings]\n{settings_text}')
    keys.write_secret_file(services.get("github")["secrets_file"], {"GH_TOKEN": SENTINEL})
    services.write_registry({"github": {"connected": True}})
    return folder


def head(folder):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder / "code", capture_output=True, text=True).stdout.strip()


def script(adapters, refs=(), assets=("demo-0.1-py3-none-any.whl",), release_id=77, tag="v1"):
    http = adapters.http
    http.script("GET", f"{API}/git/matching-refs/tags/v", 200, body=json.dumps(list(refs)).encode())
    http.script("POST", f"{API}/git/refs", 201, body=b"{}")
    http.script("POST", f"{API}/releases", 201, body=json.dumps({"id": release_id, "html_url": f"https://github.com/o/demo/releases/tag/{tag}"}).encode())
    for name in assets:
        http.script("POST", f"{API}/releases/{release_id}/assets?name={name}", 201, body=b"{}")
    http.script("GET", f"{API}/releases/tags/{tag}", 200,
                body=json.dumps({"assets": [{"name": n} for n in assets]}).encode())
    http.script("DELETE", f"{API}/releases/{release_id}", 204)
    http.script("DELETE", f"{API}/git/refs/tags/{tag}", 204)


def build_ok(adapters, name="demo-0.1-py3-none-any.whl"):
    adapters.docker.script_check("pip wheel", 0, {name: "wheel-bytes"})


@pytest.fixture
def adapters(adapters):
    """Fakes where the check container really runs/scripts the build."""
    from fakes import RealCheckDocker
    adapters.docker = RealCheckDocker()
    return adapters


def run(adapters, folder):
    return deploy.run_deploy(adapters, "demo", who="t", commit=head(folder))


def urls(adapters):
    return [(c["method"], c["url"].replace(BASE, "")) for c in adapters.http.calls]


def test_happy_release_call_sequence(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    r = run(adapters, folder)
    assert r["ok"], r["reason"]
    assert r["version"] == "v1" and r["url"].endswith("/releases/tag/v1")
    assert urls(adapters) == [
        ("GET", "/repos/o/demo/git/matching-refs/tags/v"), ("POST", "/repos/o/demo/git/refs"),
        ("POST", "/repos/o/demo/releases"),
        ("POST", "/repos/o/demo/releases/77/assets?name=demo-0.1-py3-none-any.whl"),
        ("GET", "/repos/o/demo/releases/tags/v1")]
    ref = json.loads(adapters.http.calls[1]["body"])
    assert ref == {"ref": "refs/tags/v1", "sha": head(folder)}
    rel = json.loads(adapters.http.calls[2]["body"])
    assert rel["tag_name"] == "v1" and rel["draft"] is False and rel["prerelease"] is False
    assert adapters.http.calls[3]["body"] == b"wheel-bytes"
    assert adapters.http.calls[3]["headers"]["Content-Type"] == "application/octet-stream"
    assert adapters.proxy.running() == []


def test_next_tag_numeric(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env, 'build_command = "none"\n')
    refs = [{"ref": f"refs/tags/v{n}", "object": {"sha": "b" * 40}} for n in (1, 9, 2)]
    refs += [{"ref": "refs/tags/v9.3", "object": {"sha": "c" * 40}}, {"ref": "refs/tags/vx", "object": {"sha": "d" * 40}}]
    script(adapters, refs, assets=(), release_id=5, tag="v10")
    r = run(adapters, folder)
    assert r["ok"] and r["version"] == "v10"
    assert json.loads(adapters.http.calls[1]["body"])["ref"] == "refs/tags/v10"


def test_commit_already_released_refused(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env, 'build_command = "none"\n')
    script(adapters, [{"ref": "refs/tags/v3", "object": {"sha": head(folder)}}])
    r = run(adapters, folder)
    assert not r["ok"] and "already released as v3" in r["reason"]
    assert [m for m, _ in urls(adapters)] == ["GET"]


def test_build_runs_in_check_container_not_host(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    assert run(adapters, folder)["ok"]
    assert not any("pip" in " ".join(c) for c in adapters.host.calls)
    argv = adapters.docker.argvs[0]
    assert "phoenix9-step-python:1" in argv and "pip wheel" in argv[-1]
    text = " ".join(argv)
    assert "dst=/out" in text and "release-v1/out" in text
    assert "--network" not in argv and "NET_ADMIN" in text          # firewalled, not network-less
    assert "allowed-domains" in text and not any(a.startswith("--env-file") for a in argv)


def test_build_failure_no_tag_created(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    lines = "\n".join(f"line {i}" for i in range(40))
    adapters.docker.script_check("pip wheel", 1, output=lines)
    r = run(adapters, folder)
    assert not r["ok"] and "line 39" in r["reason"]
    assert [m for m, _ in urls(adapters)] == ["GET"]


def test_upload_failure_cleans_up_tag_and_release(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    adapters.http.script("POST", f"{API}/releases/77/assets?name=demo-0.1-py3-none-any.whl", 500)
    r = run(adapters, folder)
    assert not r["ok"] and "500" in r["reason"]
    assert ("DELETE", "/repos/o/demo/releases/77") in urls(adapters)
    assert ("DELETE", "/repos/o/demo/git/refs/tags/v1") in urls(adapters)


def test_unhealthy_missing_asset_rolls_back(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    adapters.http.script("GET", f"{API}/releases/tags/v1", 200, body=json.dumps({"assets": []}).encode())
    r = run(adapters, folder)
    assert not r["ok"] and r["rolled_back"] and "missing demo-0.1" in r["reason"]
    assert ("DELETE", "/repos/o/demo/releases/77") in urls(adapters)
    assert ("DELETE", "/repos/o/demo/git/refs/tags/v1") in urls(adapters)


def test_only_declared_calls_used(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    run(adapters, folder)
    adapters.http.script("GET", f"{API}/releases/tags/v1", 200, body=json.dumps({"assets": []}).encode())
    deploy.run_deploy(adapters, "demo", who="t", commit="e" * 40)     # a second release whose health fails: rollback calls
    data = tomllib.loads((REAL / "services/github/service.toml").read_text())
    rules = proxy.parse_rules(data["proxy"]["allow"])
    assert adapters.http.calls
    for method, url in urls(adapters):
        path = url.split("?")[0]
        assert proxy.path_is_safe(path) and proxy.find_rule(rules, method, path), f"{method} {path} is not an allowed call"


def test_artefact_globs_no_symlinks_no_escape(tmp_path):
    mod = deploy.load_module(deploy.load_library(REAL / "deployers")["github-release"])
    out = tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    (out / "a.whl").write_text("a")
    (out / "b.txt").write_text("b")
    (out / "sub" / "c.whl").write_text("c")
    secret = tmp_path / "secret.whl"
    secret.write_text("s")
    (out / "link.whl").symlink_to(secret)
    (out / "linkdir").symlink_to(tmp_path)
    names = lambda pats: [p.name for p in mod.collect_artefacts(out, pats)]
    assert names([]) == ["a.whl", "b.txt", "c.whl"]
    assert names(["*.whl"]) == ["a.whl"] and names(["**/*.whl"]) == ["a.whl", "c.whl"]
    for bad in ("../*", "/etc/*", "sub/../../x"):
        with pytest.raises(DeployError):
            mod.collect_artefacts(out, [bad])


def test_no_key_anywhere(phoenix_env, lib, adapters):
    folder = make_project(phoenix_env)
    script(adapters)
    build_ok(adapters)
    r = run(adapters, folder)
    assert r["ok"]
    assert adapters.proxy.started[0]["key_len"] == len(SENTINEL)
    for call in adapters.http.calls:
        assert SENTINEL not in json.dumps({k: str(v) for k, v in call.items()})
        assert call["headers"]["X-Phoenix-Proxy-Token"] == "fake-proxy-token"
    blob = json.dumps(r) + " ".join(" ".join(c) for c in adapters.docker.argvs)
    for path in phoenix_env["home"].rglob("*"):
        if path.is_file() and "secrets" not in path.parts and path.suffix != ".env":
            blob += path.read_text(errors="replace")
    for path in phoenix_env["projects"].rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            blob += path.read_text(errors="replace")
    assert SENTINEL not in blob
