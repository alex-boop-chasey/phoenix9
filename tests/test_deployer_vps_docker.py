"""The vps-docker deployer: command order, run flags, health, rollback, preview, ports, secrets."""
from pathlib import Path

import pytest

from phoenix9 import deploy
from phoenix9.deploy import DeployError

REAL = Path(__file__).resolve().parent.parent
SENTINEL = "SENTINEL-KEY-8841-vps"
SHA = "abcdef1234567890"
NEW, OLD = "phoenix-site-demo:abcdef1", "phoenix-site-demo:1111111"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A temp library with the real deployers."""
    root = tmp_path / "lib"
    root.mkdir()
    for name in ("steps", "presets", "profiles", "services", "templates", "deployers"):
        (root / name).symlink_to(REAL / name)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    return root


@pytest.fixture
def project(phoenix_env, lib):
    """A project deployed with vps-docker, with a Dockerfile and one stored key."""
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "code").mkdir()
    (folder / "code" / "Dockerfile").write_text("FROM scratch\n")
    (folder / "phoenix.toml").write_text(
        '[deploy]\nwith = "vps-docker"\nmode = "button"\n\n[deploy.settings]\nlive_port = 8080\n')
    from phoenix9 import keys
    keys.set_key("demo", "API_KEY", SENTINEL)
    return folder


def sub(calls, *prefix):
    return [c for c in calls if c[:len(prefix)] == list(prefix)]


def docker_verbs(adapters):
    return [c[1] for c in adapters.host.calls if c[0] == "docker"]


def healthy(adapters, *ports):
    for p in ports:
        adapters.http.script("GET", f"http://127.0.0.1:{p}/", 200)


def run(adapters, **kw):
    return deploy.run_deploy(adapters, "demo", who="t", commit=SHA, **kw)


def test_happy_deploy_command_sequence(project, adapters):
    healthy(adapters, 8080, 9080)
    adapters.host.script(["docker", "inspect"], out=OLD + "\n")
    r = run(adapters)
    assert r["ok"] and r["version"] == "abcdef1" and r["url"] == "http://127.0.0.1:8080/"
    calls = adapters.host.calls
    names = [(c[1], c[-1] if c[1] != "run" else c[c.index("--name") + 1]) for c in calls]
    assert docker_verbs(adapters) == ["build", "stop", "rm", "run", "inspect", "stop", "rm", "stop", "rm", "run"]
    assert names[3] == ("run", "site-demo-check") and names[-1] == ("run", "site-demo-live")
    assert names[5:9] == [("stop", "site-demo-check"), ("rm", "site-demo-check"),
                          ("stop", "site-demo-live"), ("rm", "site-demo-live")]
    assert [c["url"] for c in adapters.http.calls] == ["http://127.0.0.1:9080/", "http://127.0.0.1:8080/"]
    assert calls[0][:2] == ["docker", "build"] and "-t" in calls[0] and NEW in calls[0]
    assert r["rolled_back"] is False


def test_build_uses_long_timeout(project, adapters):
    healthy(adapters, 8080, 9080)
    seen = []
    orig = adapters.host.run
    adapters.host.run = lambda argv, timeout=60, cwd=None: (seen.append((argv[1], timeout)), orig(argv, timeout, cwd))[1]
    run(adapters)
    assert ("build", 1800) in seen and all(t <= 1800 for _, t in seen)


def test_run_flags_loopback_limits_no_socket(project, adapters):
    healthy(adapters, 8080, 9080)
    run(adapters)
    runs = sub(adapters.host.calls, "docker", "run")
    assert len(runs) == 2
    for argv in runs:
        text = " ".join(argv)
        assert any(a.startswith("127.0.0.1:") and a.endswith(":3000") for a in argv)
        assert "--memory 512m" in text and "--cpus 1.0" in text
        assert "--log-opt max-size=10m --log-opt max-file=3" in text
        assert "phoenix9.project=demo" in text and f"phoenix9.commit={SHA}" in text
        assert "docker.sock" not in text and "--privileged" not in text and "host" not in argv
        assert "--network" not in argv
    live = runs[1]
    assert "--restart" in live and live[live.index("--restart") + 1] == "unless-stopped"
    assert "--restart" not in runs[0]
    assert "127.0.0.1:8080:3000" in live and "127.0.0.1:9080:3000" in runs[0]


def test_env_values_never_in_argv(project, adapters):
    healthy(adapters, 8080, 9080)
    seen = {}
    orig = adapters.host.run

    def spy(argv, timeout=60, cwd=None):
        if argv[:2] == ["docker", "run"] and "--env-file" in argv:
            path = Path(argv[argv.index("--env-file") + 1])
            seen["text"] = path.read_text()
        return orig(argv, timeout, cwd)
    adapters.host.run = spy
    run(adapters)
    assert all(SENTINEL not in " ".join(c) for c in adapters.host.calls)
    assert SENTINEL in seen["text"]


def test_check_unhealthy_leaves_live_untouched(project, adapters):
    healthy(adapters, 8080)      # the side port answers 404
    r = run(adapters)
    assert not r["ok"] and "live site was not touched" in r["reason"]
    assert not [c for c in adapters.host.calls if c[1] == "run" and "site-demo-live" in c and c[-1] != OLD]
    assert len(adapters.clock.sleeps) >= 5


def test_check_unhealthy_deploy_function_never_stops_live(project, adapters, lib):
    mod = deploy.load_module(deploy.get("vps-docker"))
    dctx = _dctx(project, adapters)
    with pytest.raises(DeployError, match="live site was not touched"):
        mod.deploy(dctx)
    assert not [c for c in adapters.host.calls if c[-1] == "site-demo-live"]
    assert adapters.clock.sleeps == [10.0] * 5


def _dctx(project, adapters, run_id=None, **over):
    d = deploy.get("vps-docker")
    settings = {**d["settings"], "live_port": 8080, **over}
    return deploy.DeployContext(project=deploy.ProjectRef("demo", project, {}), deployer=d, settings=settings,
                                source_dir=project / "code", commit=SHA, run_id=run_id, adapters=adapters,
                                proxy=None, env_file=None, log_path=project / "x.log")


def test_live_unhealthy_rolls_back_to_previous_image(project, adapters):
    healthy(adapters, 9080)                         # check passes, live stays 404
    adapters.host.script_seq(["docker", "inspect"], [(0, OLD + "\n", ""), (0, NEW + "\n", "")])
    r = run(adapters)
    assert not r["ok"] and r["rolled_back"]
    live_runs = [c for c in sub(adapters.host.calls, "docker", "run") if "site-demo-live" in c]
    assert live_runs[0][-1] == NEW and live_runs[-1][-1] == OLD     # switched, then put back


def test_rollback_without_previous_reports_down(project, adapters):
    mod = deploy.load_module(deploy.get("vps-docker"))
    out = mod.rollback(_dctx(project, adapters), {}, None)
    assert out == {"restored": None}
    assert not sub(adapters.host.calls, "docker", "run")
    assert sub(adapters.host.calls, "docker", "stop", "site-demo-live")


def test_rollback_uses_previous_record_version(project, adapters):
    healthy(adapters, 8080)
    mod = deploy.load_module(deploy.get("vps-docker"))
    out = mod.rollback(_dctx(project, adapters), {}, {"version": "1111111"})
    assert out == {"restored": OLD, "healthy": True}


def test_missing_dockerfile_error(project, adapters):
    (project / "code" / "Dockerfile").unlink()
    mod = deploy.load_module(deploy.get("vps-docker"))
    with pytest.raises(DeployError, match="needs a Dockerfile at the repo root"):
        mod.deploy(_dctx(project, adapters))
    assert not adapters.host.calls


def test_port_validation(project, adapters):
    mod = deploy.load_module(deploy.get("vps-docker"))
    base = deploy.get("vps-docker")["settings"]
    assert mod.ports({**base, "live_port": 8080}) == (8080, 9080, 10080)
    for bad in ({"live_port": 0}, {"live_port": 80}, {"live_port": 65000}, {"live_port": 8080, "side_port": 8080},
                {"live_port": 8080, "preview_port": 9080}):
        with pytest.raises(DeployError):
            mod.ports({**base, **bad})


def test_preview_builds_from_worktree_on_preview_port(project, adapters, phoenix_env):
    from phoenix9 import paths
    tree = paths.work("demo", "r1")
    tree.mkdir(parents=True)
    (tree / "Dockerfile").write_text("FROM scratch\n")
    healthy(adapters, 10080)
    r = deploy.run_preview(adapters, "demo", who="t", run_id="r1", commit=SHA, source_dir=tree)
    assert r["ok"] and r["url"] == "http://127.0.0.1:10080/"
    build = sub(adapters.host.calls, "docker", "build")[0]
    assert build[-1] == str(tree) and "phoenix-site-demo:preview-r1" in build
    run_ = sub(adapters.host.calls, "docker", "run")[0]
    assert "site-demo-preview" in run_ and "127.0.0.1:10080:3000" in run_ and "--restart" not in run_
    assert not [c for c in adapters.host.calls if c[-1] == "site-demo-live"]


def test_stop_preview(project, adapters):
    mod = deploy.load_module(deploy.get("vps-docker"))
    mod.stop_preview(_dctx(project, adapters, run_id="r1"), {})
    assert adapters.host.calls == [["docker", "stop", "site-demo-preview"], ["docker", "rm", "site-demo-preview"]]
