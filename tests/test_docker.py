from pathlib import Path
"""Tests for phoenix9/docker.py. They only look at the `docker run` argv and the fake runner."""
import pytest

from phoenix9 import docker, paths

IMAGE = "phoenix9-step:web"


def pairs(argv, flag):
    """Return every value that follows `flag` in argv."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


@pytest.fixture
def files(tmp_path):
    """A workspace, prompt, spec folder, env file, domains file and claude.env on disk."""
    ws = tmp_path / "ws"
    ws.mkdir()
    spec = tmp_path / "spec"
    spec.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello")
    env = tmp_path / "shop.env"
    env.write_text("STRIPE_KEY=sk_test_1234567890\n")
    domains = tmp_path / "shop.domains"
    domains.write_text("api.anthropic.com\n")
    paths.secrets().mkdir(parents=True)
    (paths.secrets() / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=secret-token-value\n")
    return {"ws": ws, "spec": spec, "prompt": prompt, "env": env, "domains": domains}


def claude_argv(files, role="builder", **kw):
    r = docker.claude_run("shop", "abcd", 3, 2, role, IMAGE, files["ws"], files["prompt"], ["claude", "-p"],
                          [files["env"]], files["domains"], files["spec"], **kw)
    return docker.build_argv(r)


def check_argv(files, firewall=True):
    r = docker.check_run("shop", "abcd", 3, 2, "check", IMAGE, files["ws"], "echo hi", files["env"],
                         files["domains"], "vol-pnpm", firewall=firewall)
    return docker.build_argv(r)


def test_container_name_includes_project():
    assert docker.container_name("shop", "abcd", 3, 2, "builder") == "phoenix9-shop-abcd-3-2-builder"


def test_claude_argv_basics(files):
    argv = claude_argv(files)
    assert argv[:5] == ["docker", "run", "--rm", "-i", "--init"]
    assert pairs(argv, "--name") == ["phoenix9-shop-abcd-3-2-builder"]
    assert pairs(argv, "--memory") == ["4g"]
    assert pairs(argv, "--cpus") == ["1.5"]
    assert pairs(argv, "--pids-limit") == ["512"]
    assert pairs(argv, "--security-opt") == ["no-new-privileges"]
    assert pairs(argv, "--cap-add") == ["NET_ADMIN", "NET_RAW"]
    assert pairs(argv, "--entrypoint") == [docker.ENTRY]
    assert "phoenix9=1" in pairs(argv, "--label")
    assert "phoenix9.project=shop" in pairs(argv, "--label")
    assert "phoenix9.run=abcd" in pairs(argv, "--label")
    assert argv[-2:] == ["claude", "-p"]


def test_image_comes_from_run(files):
    assert IMAGE in claude_argv(files)
    r = docker.claude_run("shop", "abcd", 1, 1, "builder", "other:img", files["ws"], files["prompt"], ["x"])
    assert "other:img" in docker.build_argv(r) and IMAGE not in docker.build_argv(r)


def test_limits_can_be_overridden(files):
    r = docker.claude_run("shop", "abcd", 1, 1, "builder", IMAGE, files["ws"], files["prompt"], ["x"])
    argv = docker.build_argv(r, {"memory": "8g", "cpus": "2", "pids": "100"})
    assert pairs(argv, "--memory") == ["8g"] and pairs(argv, "--memory-swap") == ["8g"]
    assert pairs(argv, "--cpus") == ["2"] and pairs(argv, "--pids-limit") == ["100"]


def test_claude_argv_env(files):
    argv = claude_argv(files)
    env = pairs(argv, "-e")
    for want in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0",
                 "HANDS_FIREWALL=1", "TZ=UTC"):
        assert want in env
    assert pairs(argv, "--env-file") == [str(paths.secrets() / "claude.env"), str(files["env"])]
    assert not any("secret-token-value" in a or "sk_test" in a for a in argv)   # values never in argv


def test_spec_mount_is_read_only_and_no_socket(files):
    mounts = pairs(claude_argv(files), "--mount")
    assert f"type=bind,src={files['spec'].resolve()},dst={docker.SPEC_MOUNT},readonly" in mounts
    assert f"type=bind,src={files['ws'].resolve()},dst=/workspace" in mounts
    assert f"type=bind,src={files['domains'].resolve()},dst={docker.DOMAINS_MOUNT},readonly" in mounts
    assert not any(".ssh" in m or "docker.sock" in m for m in mounts)


def test_docker_socket_mount_refused(files):
    r = docker.claude_run("shop", "abcd", 1, 1, "builder", IMAGE, files["ws"], files["prompt"], ["x"])
    r.mounts.append(docker.Mount("/var/run/docker.sock", "/var/run/docker.sock"))
    with pytest.raises(ValueError):
        docker.build_argv(r)


def test_scrub_setting(files):
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1" in pairs(claude_argv(files, scrub_env=True), "-e")


def test_role_in_name(files):
    assert pairs(claude_argv(files, role="checker"), "--name") == ["phoenix9-shop-abcd-3-2-checker"]


@pytest.mark.parametrize("name", ["github.env", "service-stripe.env", "service-x.env"])
def test_forbidden_env_files_refused(files, tmp_path, name):
    bad = tmp_path / name
    bad.write_text("TOKEN=abcdefghijkl\n")
    r = docker.claude_run("shop", "abcd", 1, 1, "builder", IMAGE, files["ws"], files["prompt"], ["x"], [bad])
    with pytest.raises(ValueError):
        docker.build_argv(r)


def test_check_argv_with_firewall(files):
    argv = check_argv(files)
    assert pairs(argv, "--name") == ["phoenix9-shop-abcd-3-2-check"]
    assert pairs(argv, "--cap-add") == ["NET_ADMIN", "NET_RAW"]
    assert pairs(argv, "--env-file") == [str(files["env"])]
    assert not any(e.startswith("CLAUDE_") for e in pairs(argv, "-e"))
    assert "type=volume,src=vol-pnpm,dst=/pnpm-store" in pairs(argv, "--mount")
    assert argv[-3:] == ["bash", "-c", "echo hi"]


def test_check_argv_without_firewall(files):
    argv = check_argv(files, firewall=False)
    assert "--cap-add" not in argv
    assert pairs(argv, "--network") == ["none"]
    assert "HANDS_FIREWALL=0" in pairs(argv, "-e")


def test_check_refuses_claude_env(files):
    with pytest.raises(ValueError):
        docker.check_run("shop", "abcd", 1, 1, "check", IMAGE, files["ws"], "true",
                         paths.secrets() / "claude.env", None, "vol")


def test_missing_bind_source_and_comma(tmp_path):
    with pytest.raises(FileNotFoundError):
        docker.Mount(tmp_path / "nope", "/x").arg()
    d = tmp_path / "a,b"
    d.mkdir()
    with pytest.raises(ValueError):
        docker.Mount(d, "/x").arg()


def test_agent_never_root():
    uid, gid = docker.agent_ids()
    assert uid != 0 and gid != 0


def test_agent_never_root_when_phoenix_is_root(monkeypatch):
    monkeypatch.setattr(docker.os, "getuid", lambda: 0)
    assert docker.agent_ids() == (1000, 1000)


def test_run_check_container_uses_runner_and_scrubs(files, adapters):
    d = adapters.docker
    d.outputs = ["key is sk_test_1234567890 ok\n"]
    d.exit_codes = [3]
    rc, out = docker.run_check_container(d, "shop", "abcd", 3, 1, IMAGE, files["ws"], "make test",
                                         files["env"], files["domains"], 5)
    assert rc == 3
    assert "sk_test_1234567890" not in out.read_text()
    assert out == paths.runs("shop") / "abcd" / "logs" / "3-1-check.txt"
    argv = d.argvs[0]
    assert pairs(argv, "--name") == ["phoenix9-shop-abcd-3-1-check"]
    calls = [c for c in d.calls if c[0] != "chown"]  # chown only happens when the tests run as root
    assert calls[0][0] == "rm" and calls[-1] == ("volume_rm", ("phoenix9-shop-abcd-3-1-check-pnpm",), {})
    assert d.volumes == []


def test_timeout_rc_passes_through(files, adapters):
    d = adapters.docker
    d.exit_codes = [docker.TIMEOUT_RC]
    rc, _ = docker.run_claude_container(d, "shop", "abcd", 1, 1, "builder", IMAGE, files["ws"], files["prompt"],
                                        ["claude"], 1, env_files=[files["env"]])
    assert rc == 124
    run_call = [c for c in d.calls if c[0] == "run"][0]
    assert run_call[1][3] == 60                    # timeout in seconds
    assert d.removed[0] == d.removed[-1] == "phoenix9-shop-abcd-1-1-builder"


def test_cleanup_orphans(adapters):
    d = adapters.docker
    d.orphans = ["c1", "c2"]
    assert docker.cleanup_orphans(d, "abcd") == 2
    assert d.removed == ["c1", "c2"]
    assert ("ps_ids", ("phoenix9.run=abcd",), {}) in d.calls


def test_real_adapter_has_docker_runner():
    from phoenix9 import adapters
    assert isinstance(adapters.real().docker, docker.DockerRunner)


def test_probe_firewall_reports_failures(adapters):
    d = adapters.docker
    d.outputs = ["LEAK ip-blocked anthropic=404\n"]
    d.exit_codes = [1]
    failures = docker.probe_firewall(d, IMAGE)
    assert "egress blocked for non-allowlisted sites (example.com)" in failures
    assert docker.probe_firewall(d, IMAGE)[0].startswith("egress blocked")   # empty output also fails


def test_firewall_checks_good_and_leak():
    good = ("blocked ip-blocked anthropic=404 cannot-flush no-sudo v6-blocked dns-allowed-ok "
            "dns-random-blocked dns-direct-blocked-1.1.1.1+udp dns-direct-blocked-1.1.1.1+tcp "
            "dns-direct-blocked-8.8.8.8+udp dns-direct-blocked-8.8.8.8+tcp dnsmasq-running dnsmasq-survived "
            "dnsconf-readonly ssh-blocked ghip-blocked gh-dns-blocked github=000 host-blocked 1000")
    assert all(ok for ok, _ in docker.firewall_checks(good))
    leak = good.replace("blocked ip-blocked", "LEAK ip-blocked", 1)
    assert [l for ok, l in docker.firewall_checks(leak) if not ok] == [
        "egress blocked for non-allowlisted sites (example.com)"]


def test_domains_merged_and_deduplicated():
    assert docker.merge_domains(["api.stripe.com", "API.anthropic.com"], ["api.stripe.com", "fonts.x.com", " "]) == [
        "api.anthropic.com", "api.stripe.com", "fonts.x.com"]


def test_write_domains_file():
    path = docker.write_domains_file("shop", ["registry.npmjs.org"], ["api.stripe.com", "registry.npmjs.org"])
    assert path == paths.home() / "cache" / "domains" / "shop.domains"
    assert path.read_text().splitlines() == ["api.anthropic.com", "registry.npmjs.org", "api.stripe.com"]
    assert docker.write_domains_file("blog").read_text().splitlines() == list(docker.BUILTIN_DOMAINS)


def test_hand_to_agent_chowns_only_as_root(adapters, tmp_path, monkeypatch):
    d = adapters.docker
    monkeypatch.setattr(docker.os, "getuid", lambda: 1000)
    docker.hand_to_agent(d, tmp_path)
    assert not [c for c in d.calls if c[0] == "chown"]
    monkeypatch.setattr(docker.os, "getuid", lambda: 0)
    docker.hand_to_agent(d, tmp_path)
    assert [c for c in d.calls if c[0] == "chown"]


def test_hand_writable_mounts_chowns_only_writable_folders(adapters, tmp_path, monkeypatch):
    d = adapters.docker
    monkeypatch.setattr(docker.os, "getuid", lambda: 0)
    out, ro, f = tmp_path / "out", tmp_path / "ro", tmp_path / "file.txt"
    out.mkdir(); ro.mkdir(); f.write_text("x")
    docker.hand_writable_mounts(d, [docker.Mount(out, "/out", ro=False), docker.Mount(ro, "/in"),
                                    docker.Mount(f, "/f", ro=False), docker.Mount("vol", "/v", ro=False)])
    chowned = [c for c in d.calls if c[0] == "chown"]
    assert len(chowned) == 1 and str(out) in str(chowned[0])


def test_probe_that_never_ran_reports_one_stopped_early_line(adapters):
    d = adapters.docker
    d.outputs, d.exit_codes = ["hands: firewall setup failed:\nERROR: bad proxy line\nsomething else\n"], [90]
    assert docker.probe_firewall(d, IMAGE) == [
        "the probe container stopped early (exit 90): ERROR: bad proxy line"]
    d.outputs, d.exit_codes = [""], [125]
    assert docker.probe_firewall(d, IMAGE) == ["the probe container stopped early (exit 125): no output"]


def _linked_worktree(tmp_path):
    import subprocess
    main = tmp_path / "main"
    main.mkdir()
    g = lambda *a, cwd=main: subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                            check=True, capture_output=True)
    g("init", "-q", "-b", "main")
    (main / "a.txt").write_text("a")
    g("add", "a.txt")
    g("commit", "-qm", "one")
    wt = tmp_path / "wt"
    g("worktree", "add", "-q", "-b", "phoenix/r1", str(wt))
    return main, wt


def test_git_dir_mounts_mounts_the_main_git_folder_read_only_at_the_same_path(tmp_path):
    main, wt = _linked_worktree(tmp_path)
    mounts = docker.git_dir_mounts(wt)
    assert len(mounts) == 1
    m = mounts[0]
    assert m.ro is True and Path(m.src) == (main / ".git").resolve() and m.dst == str((main / ".git").resolve())


def test_git_dir_mounts_nothing_for_a_plain_checkout_or_no_git(tmp_path):
    main, _ = _linked_worktree(tmp_path)
    assert docker.git_dir_mounts(main) == []
    assert docker.git_dir_mounts(tmp_path) == []


def test_check_and_session_containers_get_git_working(tmp_path):
    _, wt = _linked_worktree(tmp_path)
    r = docker.check_run("p", "r1", 1, 1, "verify", "img", wt, "true", None, None, "store")
    assert any(m.dst.endswith("/main/.git") and m.ro for m in r.mounts)
    assert r.env["GIT_CONFIG_KEY_0"] == "safe.directory"
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x")
    s = docker.claude_run("p", "r1", 1, 1, "builder", "img", wt, prompt, ["claude"])
    assert any(m.dst.endswith("/main/.git") and m.ro for m in s.mounts)
    assert s.env["GIT_CONFIG_VALUE_0"] == "*"


def test_every_check_container_turns_colour_off(files):
    for role in ("acceptance", "verify", "red-check", "full-suite", "baseline"):
        r = docker.check_run("p", "r1", 1, 1, role, "img", files["ws"], "true", None, None, "store")
        assert r.env["NO_COLOR"] == "1" and r.env["FORCE_COLOR"] == "0", role
    assert "NO_COLOR=1" in pairs(check_argv(files), "-e") and "FORCE_COLOR=0" in pairs(check_argv(files), "-e")


# ------------------------------------------------------------- check containers and CPU cores
def run_check(files, adapters, cores, setting=None):
    """Run a fake check container on a host with `cores` cores; return the docker argv."""
    if setting is not None:
        paths.config().mkdir(parents=True, exist_ok=True)
        (paths.config() / "global.toml").write_text(f"[limits]\ncheck_cpus = {setting}\n")
    d = adapters.docker
    d.cores = cores
    docker.run_check_container(d, "shop", "abcd", 3, 1, IMAGE, files["ws"], "make test", files["env"],
                               files["domains"], 5)
    return d.argvs[-1]


@pytest.mark.parametrize("cores", [2, 8])
def test_check_container_uses_every_core_by_default(files, adapters, cores):
    argv = run_check(files, adapters, cores)
    assert pairs(argv, "--cpus") == [str(cores)]
    assert f"PHOENIX_CPUS={cores}" in pairs(argv, "-e")


def test_check_container_fixed_number(files, adapters):
    argv = run_check(files, adapters, 8, setting="2.5")
    assert pairs(argv, "--cpus") == ["2.5"] and "PHOENIX_CPUS=2" in pairs(argv, "-e")
    assert "PHOENIX_CPUS=1" in pairs(run_check(files, adapters, 8, setting="0.5"), "-e")


def test_ai_container_limits_unchanged(files, adapters):
    adapters.docker.cores = 8
    assert pairs(claude_argv(files), "--cpus") == ["1.5"]
    assert not any(e.startswith("PHOENIX_CPUS") for e in pairs(claude_argv(files), "-e"))


@pytest.mark.parametrize("bad", ["0.1", "9", '"lots"', "true", "-1"])
def test_bad_check_cpus_refused_plainly(files, adapters, bad):
    with pytest.raises(ValueError, match="limits.check_cpus must be"):
        run_check(files, adapters, 8, setting=bad)


# ------------------------------------------------------------- time limits and failure records
def failures():
    """The `command.failed` events recorded so far."""
    import json
    if not paths.events().exists():
        return []
    return [e for e in map(json.loads, paths.events().read_text().splitlines()) if e["type"] == "command.failed"]


def fake_docker(tmp_path, monkeypatch, body):
    """Point DockerRunner at a small python program standing in for docker."""
    import sys
    prog = tmp_path / "fake-docker"
    prog.write_text(f"#!{sys.executable}\nimport sys, time\n{body}\n")
    prog.chmod(0o755)
    monkeypatch.setattr(docker, "DOCKER", str(prog))


def test_short_docker_calls_have_time_limits(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch, "time.sleep(30)")
    monkeypatch.setattr(docker, "DOCKER_CALL_TIMEOUT_S", 0.3)
    d = docker.DockerRunner()
    assert d.ps_ids("phoenix9") == [] and d.image_exists("x") is False and d.image_id("x") == ""
    assert d.image_label("x", "y") == ""
    d.rm("c1"), d.stop("c1"), d.volume_rm("v1")          # they return instead of hanging
    with pytest.raises(docker.DockerError, match="timed out after 0.3s"):
        d.volume_create("v1", ["phoenix9=1"])


def test_every_docker_call_passes_its_time_limit(monkeypatch, tmp_path):
    from phoenix9 import proc
    seen = []
    monkeypatch.setattr(proc, "run", lambda argv, **kw: seen.append((list(argv), kw.get("timeout"))) or
                        proc.Result(0, "172.17.0.1 172.17.0.0/16 docker0", ""))
    d = docker.DockerRunner()
    d.rm("c"), d.stop("c"), d.ps_ids("l"), d.volume_create("v", []), d.volume_rm("v")
    d.chown(tmp_path, 1, 1), d.image_exists("t"), d.image_id("t"), d.image_label("t", "l")
    limits = [t for _, t in seen]
    assert limits == [60, 60, 60, 60, 60, docker.CHOWN_TIMEOUT_S, 60, 60, 60] and docker.CHOWN_TIMEOUT_S == 600
    stop = next(a for a, _ in seen if a[1] == "stop")
    assert stop[2:4] == ["-t", "20"]                 # the 20 s grace stays inside the 60 s limit


def test_volume_create_failure_says_why(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch, "print('Error response from daemon: no space left', file=sys.stderr)\n"
                                       "sys.exit(1)")
    with pytest.raises(docker.DockerError) as e:
        docker.DockerRunner().volume_create("v1", ["phoenix9=1"])
    assert str(e.value) == ("Creating the build's package store failed (exit code 1): "
                            "Error response from daemon: no space left")
    assert [f["data"]["what"] for f in failures()] == [docker.VOLUME_WHAT]


def test_probe_failures_record_nothing(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch, "sys.exit(1)")
    d = docker.DockerRunner()
    d.rm("c1"), d.stop("c1"), d.volume_rm("v1"), d.ps_ids("l"), d.image_exists("x")
    assert failures() == []


def test_failed_image_build_records_the_log_tail(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch, "print('step 3/9 npm ERR! network down'); sys.exit(1)")
    log = tmp_path / "build.log"
    rc = docker.DockerRunner().build(tmp_path / "Dockerfile", "phoenix9-step:web", tmp_path, {}, log)
    assert rc == 1
    [f] = failures()
    assert f["data"]["what"] == "Building the phoenix9-step:web toolbox image"
    assert f["data"]["program"] == "fake-docker build" and "network down" in f["data"]["stderr_tail"]


def test_failing_claude_container_records_one_event_with_the_step(files, adapters):
    from phoenix9 import proc
    d = adapters.docker
    d.exit_codes = [1]
    d.errors = ["Error: token secret-token-value was refused\n"]
    with proc.context(project="shop", run="abcd", task=3, step="build"):
        rc, _ = docker.run_claude_container(d, "shop", "abcd", 3, 1, "builder", IMAGE, files["ws"], files["prompt"],
                                            ["claude"], 1, env_files=[files["env"]])
    assert rc == 1
    [f] = failures()
    assert (f["project"], f["run"], f["task"], f["step"]) == ("shop", "abcd", 3, "build")
    assert f["data"]["what"] == "AI session (builder)" and f["data"]["exit_code"] == 1
    assert "was refused" in f["data"]["stderr_tail"] and "secret-token-value" not in f["data"]["stderr_tail"]


def test_working_claude_container_records_nothing(files, adapters):
    docker.run_claude_container(adapters.docker, "shop", "abcd", 3, 1, "builder", IMAGE, files["ws"],
                                files["prompt"], ["claude"], 1, env_files=[files["env"]])
    assert failures() == []


@pytest.mark.parametrize("code,recorded", [(1, False), (2, False), (125, True), (124, True), (137, True)])
def test_check_container_records_only_when_docker_could_not_run_it(files, adapters, code, recorded):
    d = adapters.docker
    d.exit_codes = [code]
    d.outputs = ["docker: Error response from daemon: no such image\n"]
    rc, _ = docker.run_check_container(d, "shop", "abcd", 3, 1, IMAGE, files["ws"], "make test",
                                       files["env"], files["domains"], 5)
    assert rc == code
    found = failures()
    assert len(found) == (1 if recorded else 0)
    if recorded:
        assert found[0]["data"]["what"] == "Check container (check)" and "no such image" in found[0]["data"]["stderr_tail"]
