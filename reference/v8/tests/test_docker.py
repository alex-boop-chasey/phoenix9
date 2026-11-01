"""Tests for phoenix/docker.py. They only look at the `docker run` argv; no Docker is started."""
from pathlib import Path

import pytest

from phoenix import config, docker, plan

SETTINGS = dict(config.DEFAULTS)


def pairs(argv: list[str], flag: str) -> list[str]:
    """Return every value that follows `flag` in argv."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


@pytest.fixture
def files(tmp_path):
    """A workspace, prompt, project env file, domains file and claude.env on disk."""
    ws = tmp_path / "ws"
    ws.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello")
    env = tmp_path / "shop.env"
    env.write_text("STRIPE_KEY=sk_test_1234567890\n")
    domains = tmp_path / "shop.domains"
    domains.write_text("api.anthropic.com\n")
    cfg = config.paths().config
    cfg.mkdir(parents=True)
    (cfg / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=secret-token-value\n")
    return {"ws": ws, "prompt": prompt, "env": env, "domains": domains}


def claude_argv(files, role="builder"):
    r = docker.claude_run("abcd", 3, 2, role, files["ws"], files["prompt"], [files["env"]], files["domains"])
    return docker.build_argv(r, SETTINGS)


def check_argv(files, firewall=True):
    r = docker.check_run("abcd", 3, 2, "check", files["ws"], "echo hi", files["env"], files["domains"],
                         "phoenix-abcd-3-2-check-pnpm", firewall=firewall)
    return docker.build_argv(r, SETTINGS)


def test_container_name_format():
    assert docker.container_name("abcd", 3, 2, "builder") == "phoenix-abcd-3-2-builder"


def test_claude_argv_basics(files):
    argv = claude_argv(files)
    assert argv[:5] == ["docker", "run", "--rm", "-i", "--init"]
    assert pairs(argv, "--name") == ["phoenix-abcd-3-2-builder"]
    assert pairs(argv, "--memory") == ["4g"]
    assert pairs(argv, "--cpus") == ["1.5"]
    assert pairs(argv, "--pids-limit") == ["512"]
    assert pairs(argv, "--security-opt") == ["no-new-privileges"]
    assert pairs(argv, "--cap-add") == ["NET_ADMIN", "NET_RAW"]
    assert "--network" not in argv
    assert pairs(argv, "--entrypoint") == [docker.ENTRY]
    assert "phoenix-step:0.6.0" in argv


def test_claude_argv_env(files):
    argv = claude_argv(files)
    env = pairs(argv, "-e")
    for want in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0",
                 "HANDS_FIREWALL=1", "TZ=UTC"):
        assert want in env
    env_files = pairs(argv, "--env-file")
    assert env_files == [str(config.paths().config / "claude.env"), str(files["env"])]
    assert not any("secret-token-value" in a or "sk_test" in a for a in argv)   # values never in argv


def test_claude_argv_mounts(files):
    argv = claude_argv(files)
    mounts = pairs(argv, "--mount")
    ws = files["ws"].resolve()
    assert f"type=bind,src={ws},dst=/workspace" in mounts
    assert f"type=bind,src={files['prompt'].resolve()},dst={docker.PROMPT_MOUNT},readonly" in mounts
    assert f"type=bind,src={files['domains'].resolve()},dst=/etc/hands/allowed-domains,readonly" in mounts
    assert f"type=bind,src={docker.HOOKS_DIR},dst={docker.HOOKS_MOUNT},readonly" in mounts
    tdir = config.paths().runs / "abcd" / "prompts" / "3-2-builder"
    assert f"type=bind,src={tdir.resolve()},dst=/home/node/.claude/projects" in mounts
    assert any(m.endswith(",dst=/pnpm-store") for m in mounts)
    assert not any(".ssh" in m or "docker.sock" in m for m in mounts)


def test_claude_argv_runs_build_command(files):
    argv = claude_argv(files)
    tail = argv[argv.index("phoenix-step:0.6.0") + 1:]
    assert tail[:2] == ["sh", "-c"]
    assert "claude" in tail and "--bare" not in tail
    assert docker.PROMPT_MOUNT in tail and "/workspace" in tail


def test_scrub_setting(files):
    r = docker.claude_run("abcd", 3, 2, "builder", files["ws"], files["prompt"], [], None, scrub=True)
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1" in pairs(docker.build_argv(r, SETTINGS), "-e")


def test_role_in_name(files):
    assert pairs(claude_argv(files, role="checker"), "--name") == ["phoenix-abcd-3-2-checker"]


def test_github_env_refused(files, tmp_path):
    gh = tmp_path / "github.env"
    gh.write_text("GH_TOKEN=x\n")
    r = docker.claude_run("abcd", 1, 1, "builder", files["ws"], files["prompt"], [gh], None)
    with pytest.raises(ValueError):
        docker.build_argv(r, SETTINGS)


def test_check_argv_with_firewall(files):
    argv = check_argv(files)
    assert pairs(argv, "--name") == ["phoenix-abcd-3-2-check"]
    assert pairs(argv, "--cap-add") == ["NET_ADMIN", "NET_RAW"]
    assert pairs(argv, "--env-file") == [str(files["env"])]           # no claude.env
    assert not any("claude.env" in a for a in argv)
    assert not any(e.startswith("CLAUDE_") for e in pairs(argv, "-e"))
    mounts = pairs(argv, "--mount")
    assert "type=volume,src=phoenix-abcd-3-2-check-pnpm,dst=/pnpm-store" in mounts
    assert argv[-3:] == ["bash", "-c", "echo hi"]


def test_check_argv_without_firewall(files):
    argv = check_argv(files, firewall=False)
    assert "NET_ADMIN" not in argv and "NET_RAW" not in argv and "--cap-add" not in argv
    assert pairs(argv, "--network") == ["none"]
    assert "HANDS_FIREWALL=0" in pairs(argv, "-e")
    assert not any("claude.env" in a for a in argv)


def test_check_refuses_claude_env(files):
    with pytest.raises(ValueError):
        docker.check_run("abcd", 1, 1, "check", files["ws"], "true", config.paths().config / "claude.env",
                         None, "vol")


def test_missing_bind_source_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        docker.Mount(tmp_path / "nope", "/x").arg()


def test_comma_in_mount_path_fails(tmp_path):
    d = tmp_path / "a,b"
    d.mkdir()
    with pytest.raises(ValueError):
        docker.Mount(d, "/x").arg()


def test_agent_never_root():
    uid, gid = docker.agent_ids()
    assert uid != 0 and gid != 0


def test_firewall_checks_good_and_leak():
    good = ("blocked ip-blocked anthropic=404 cannot-flush no-sudo v6-blocked dns-allowed-ok "
            "dns-random-blocked dns-direct-blocked-1.1.1.1+udp dns-direct-blocked-1.1.1.1+tcp "
            "dns-direct-blocked-8.8.8.8+udp dns-direct-blocked-8.8.8.8+tcp dnsmasq-running dnsmasq-survived "
            "dnsconf-readonly ssh-blocked ghip-blocked gh-dns-blocked github=000 host-blocked 1000")
    assert all(ok for ok, _ in docker.firewall_checks(good))
    leak = good.replace("blocked ip-blocked", "LEAK ip-blocked", 1)
    failed = [label for ok, label in docker.firewall_checks(leak) if not ok]
    assert failed == ["egress blocked for non-allowlisted sites (example.com)"]
    no_api = good.replace("anthropic=404", "anthropic=000")
    assert [l for ok, l in docker.firewall_checks(no_api) if not ok] == ["api.anthropic.com reachable"]


def test_write_domains_file():
    p = plan.Plan(repo="alex/shop", sites=["api.stripe.com", "registry.npmjs.org", "fonts.googleapis.com"])
    path = docker.write_domains_file(p)
    assert path == config.paths().config / "projects" / "shop.domains"
    assert path.read_text().splitlines() == [
        "api.anthropic.com", "registry.npmjs.org", "api.stripe.com", "fonts.googleapis.com"]


def test_write_domains_file_no_sites():
    path = docker.write_domains_file(plan.Plan(repo="alex/blog"))
    assert path.read_text().splitlines() == list(docker.BUILTIN_DOMAINS)


def test_doctor_prints_failures(monkeypatch, capsys):
    from phoenix.__main__ import main
    monkeypatch.setattr(docker, "probe_firewall", lambda: ["api.anthropic.com reachable"])
    assert main(["doctor"]) == 1
    assert "api.anthropic.com reachable" in capsys.readouterr().out
    monkeypatch.setattr(docker, "probe_firewall", lambda: [])
    assert main(["doctor"]) == 0
    assert capsys.readouterr().out.startswith("OK")
