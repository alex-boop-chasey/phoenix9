"""Tests for `phoenix doctor`: every check on healthy fakes, then each one broken in turn."""
import json
import os
import subprocess
from collections import namedtuple

import pytest

from phoenix9 import addresses, claude, doctor, paths
from phoenix9.__main__ import main

PROBE_OK = ("blocked ip-blocked anthropic=200 cannot-flush no-sudo v6-blocked dns-allowed-ok dns-random-blocked "
            "dns-direct-blocked-1.1.1.1+udp dns-direct-blocked-1.1.1.1+tcp dns-direct-blocked-8.8.8.8+udp "
            "dns-direct-blocked-8.8.8.8+tcp dnsmasq-running dnsmasq-survived dnsconf-readonly ssh-blocked "
            "ghip-blocked gh-dns-blocked github=000 host-blocked proxy-reachable 1000\n")
IMAGE = "phoenix9-step-python:1"


def session_log(skills=("advisor",)) -> str:
    init = {"type": "system", "subtype": "init", "claude_code_version": "2.1.301", "slash_commands": [],
            "skills": list(skills)}
    done = {"type": "result", "subtype": "success", "is_error": False, "result": "OK", "session_id": "s1",
            "num_turns": 1, "total_cost_usd": 0.001}
    return json.dumps(init) + "\n" + json.dumps(done) + "\n"


def tag_install(adapters, tag="v9.1"):
    """Make the installed copy a git repo sitting on a release tag."""
    inst = paths.install()
    inst.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"], ["tag", tag]):
        subprocess.run(["git", *argv], cwd=inst, check=True, env=env)


def LAUNCHER():
    """Where the doctor expects the installed chat launcher."""
    return paths.install() / "deploy" / "chat-launch.sh"


AGENT_SOCK = "/tmp/cc-socks-0/x.sock"
AGENT_FOLDER = "/srv/projects/home"
AGENT_SID = "aaaaaaaa-1111-4111-8111-111111111111"
AGENT_TRANSCRIPT = "/root/.claude/projects/-srv-projects-home/%s.jsonl" % AGENT_SID


def healthy_agent(h):
    """Fake a running agent: session entry, private socket (folder 0700, socket 0600), clean transcript, set-up folder."""
    h.pids.add(77)
    h.files["/root/.claude/sessions/77.json"] = json.dumps({
        "pid": 77, "cwd": AGENT_FOLDER, "name": "Phoenix agent", "status": "idle",
        "messagingSocketPath": AGENT_SOCK, "kind": "interactive", "sessionId": AGENT_SID})
    h.files[AGENT_SOCK] = ""
    h.stats["/tmp/cc-socks-0"] = {"mode": 0o700, "uid": 0}
    h.stats[AGENT_SOCK] = {"mode": 0o600, "uid": 0}
    h.files[AGENT_TRANSCRIPT] = "".join(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n"
                                        for _ in range(20))
    h.files[f"{AGENT_FOLDER}/CLAUDE.md"] = "x"
    h.files[f"{AGENT_FOLDER}/.claude/settings.json"] = "{}"


@pytest.fixture
def healthy(adapters, phoenix_env, monkeypatch):
    """Healthy fakes: services up, API answers, HOME laid out, image built, probe and session succeed."""
    home = phoenix_env["home"]
    for name in doctor.HOME_FOLDERS:
        (home / name).mkdir(exist_ok=True)
    for name in ("secrets", "keys"):
        (home / name).chmod(0o700)
    (home / "secrets" / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-secret-value\n")
    (home / "secrets" / "claude.env").chmod(0o600)
    proj = phoenix_env["projects"] / "demo"
    proj.mkdir()
    (proj / "phoenix.toml").write_text('profile = "python-script"\n')
    host = adapters.host
    host.script(["systemctl", "is-active"], 0, "active\nactive\n")
    host.script(["systemctl", "cat"], 0, "[Unit]\n")
    host.script(["systemctl", "cat", doctor.CHAT_UNIT_FILE], 0, f"[Service]\nExecStart={LAUNCHER()} %i\n")
    host.stats[str(LAUNCHER())] = {"mode": 0o755, "uid": 0}
    for pid, name in ((101, "phoenix-api"), (102, "phoenix-runner")):
        host.script(["systemctl", "show", "-p", "MainPID", "--value", name], 0, f"{pid}\n")
        host.files[f"/proc/{pid}/environ"] = "PATH=/usr/bin\0HOME=/root\0PHOENIX_HOME=/var/lib/phoenix9\0"
    host.script(["df"], 0, "    Avail\n 90000000000\n")
    adapters.http.script("GET", "http://127.0.0.1:8095/api/health", 200,
                         body=json.dumps({"ok": True, "tag": "v9.1", "origins_digest": addresses.origins_digest(
                             ["https://phoenix.rebirthwebdesign.com.au"])}).encode())
    adapters.docker.images[IMAGE] = {}
    adapters.docker.outputs[:] = [PROBE_OK, session_log()]
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda p: Usage(10**12, 0, 50 * doctor.GB))
    tag_install(adapters)
    healthy_agent(adapters.host)
    return adapters


@pytest.fixture
def fake_ops(healthy, monkeypatch):
    """Make the CLI use the healthy fakes."""
    monkeypatch.setattr("phoenix9.ops.common.make_adapters", lambda: healthy)
    return healthy


def by_name(data):
    return {c["name"]: c for c in data["checks"]}


def test_all_checks_pass_with_healthy_fakes(fake_ops, capsys):
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "All good" in out and "PROBLEM" not in out
    assert out.count("OK") >= len(doctor.CHECKS_BY_MODE["full"])


def _break_services(a, home):
    a.host.script(["systemctl", "is-active"], 3, "active\ninactive\n")


def _break_api(a, home):
    a.http.script("GET", "http://127.0.0.1:8095/api/health", 502)


def _break_home(a, home):
    (home / "keys").rmdir()


def _break_secrets(a, home):
    (home / "secrets" / "claude.env").unlink()


def _break_images(a, home):
    a.docker.images.clear()


def _break_firewall(a, home):
    a.docker.outputs[0] = PROBE_OK.replace("host-blocked", "LEAK-HOST")


def _break_claude(a, home):
    a.docker.outputs[1] = "not json\n"


def _break_disk(a, home):
    a.host.script(["df"], 0, "Avail\n 1000000000\n")


def _break_service_home(a, home):
    a.host.files["/proc/102/environ"] = "PATH=/usr/bin\0PHOENIX_HOME=/var/lib/phoenix9\0"


def _break_updater(a, home):
    a.host.script(["systemctl", "cat"], 1, "", "no such unit")


def _break_agent_unit(a, home):
    a.host.script(["systemctl", "is-active", "claude-rc@home"], 3, "inactive\n")


def _break_agent_session(a, home):
    a.host.pids.clear()


def _break_agent_socket(a, home):
    a.host.stats[AGENT_SOCK] = {"mode": 0o666, "uid": 0}


def _break_agent_transcript(a, home):
    a.host.files[AGENT_TRANSCRIPT] += "not json\n" * 5


def _break_agent_folder(a, home):
    del a.host.files[f"{AGENT_FOLDER}/CLAUDE.md"]


@pytest.mark.parametrize("check,breaker", [
    ("services", _break_services), ("api", _break_api), ("home", _break_home), ("secrets", _break_secrets),
    ("images", _break_images), ("firewall", _break_firewall), ("claude", _break_claude),
    ("disk", _break_disk), ("updater", _break_updater), ("service-home", _break_service_home),
    ("agent-unit", _break_agent_unit), ("agent-session", _break_agent_session), ("agent-socket", _break_agent_socket),
    ("agent-transcript", _break_agent_transcript), ("agent-folder", _break_agent_folder)])
def test_each_check_failure_reported_with_fix(healthy, phoenix_env, check, breaker):
    breaker(healthy, phoenix_env["home"])
    data = doctor.run_checks(healthy, "full")
    found = by_name(data)
    assert not data["ok"] and not found[check]["ok"]
    assert found[check]["fix"] and found[check]["detail"]
    others = [c for n, c in found.items() if n != check and n not in ("advisor", "firewall", "claude")]
    assert any(c["ok"] for c in others)                       # the others still ran
    assert len(data["checks"]) == len(doctor.CHECKS_BY_MODE["full"])


def test_a_crashing_check_does_not_stop_the_others(healthy, monkeypatch):
    monkeypatch.setitem(doctor.CHECKS, "services", lambda ctx: 1 / 0)
    data = by_name(doctor.run_checks(healthy, "quick"))
    assert not data["services"]["ok"] and data["api"]["ok"] and data["disk"]["ok"]


def test_for_update_mode_runs_no_claude_session_and_checks_version(healthy):
    data = doctor.run_checks(healthy, "for-update")
    assert data["ok"], data
    assert [c["name"] for c in data["checks"]] == list(doctor.CHECKS_BY_MODE["for-update"])
    assert not any(c[0] == "run_step" for c in healthy.docker.calls)
    assert len(healthy.docker.argvs) == 1 and not any("claude" in " ".join(a) for a in healthy.docker.argvs[1:])
    healthy.http.script("GET", "http://127.0.0.1:8095/api/health", 200, body=b'{"ok": true, "tag": "v9.0"}')
    healthy.docker.outputs[:] = [PROBE_OK]
    api = by_name(doctor.run_checks(healthy, "for-update"))["api"]
    assert not api["ok"] and "v9.0" in api["detail"]


def test_quick_mode_subset(healthy):
    data = doctor.run_checks(healthy, "quick")
    assert [c["name"] for c in data["checks"]] == ["services", "service-home", "api", "origins", "upstream", "home",
                                                     "secrets", "disk", "agentkit-service", "agentkit-key", "agentkit-spend"]
    assert healthy.docker.argvs == [] and healthy.proxy.started == []


def test_firewall_check_uses_temporary_proxy_and_stops_it(healthy):
    assert by_name(doctor.run_checks(healthy, "for-update"))["firewall"]["ok"]
    (started,) = healthy.proxy.started
    assert started["bind"] == "172.17.0.1" and started["rules"] == () and started["key_seen"]
    assert healthy.proxy.stopped == ["doctor"] and healthy.proxy.running() == []
    argv = " ".join(healthy.docker.argvs[0])
    assert "allowed-proxy" in argv


def test_firewall_proxy_stopped_even_when_probe_fails(healthy):
    healthy.docker.outputs[0] = PROBE_OK.replace("proxy-reachable", "PROXY-UNREACHABLE")
    data = by_name(doctor.run_checks(healthy, "for-update"))
    assert not data["firewall"]["ok"] and "proxy" in data["firewall"]["detail"]
    assert healthy.proxy.running() == []


UFW_ON = ("Status: active\n\nTo                         Action      From\n--                         ------      ----\n"
          "22/tcp                     ALLOW       Anywhere\n")
UFW_RULE = "172.17.0.1 47100:47199/tcp on docker0 ALLOW       172.17.0.0/16              # phoenix9 key proxy\n"
EXPECTED_RULE = ("ufw allow in on docker0 from 172.17.0.0/16 to 172.17.0.1 port 47100:47199 proto tcp "
                 "comment 'phoenix9 key proxy'")


def test_proxy_unreachable_fix_gives_the_ufw_rule_and_lists_only_failures(healthy):
    healthy.docker.outputs[0] = PROBE_OK.replace("proxy-reachable", "PROXY-UNREACHABLE")
    fw = by_name(doctor.run_checks(healthy, "for-update"))["firewall"]
    assert fw["detail"] == "failed checks: the allowed key proxy address is reachable"
    assert EXPECTED_RULE in fw["fix"] and "Rebuild" not in fw["fix"]


def test_probe_container_stopped_early_is_reported_plainly(healthy):
    healthy.docker.outputs[0] = ("hands: firewall setup failed:\nResolving api.anthropic.com\n"
                                 "ERROR: Firewall verification failed - unable to reach the key proxy at "
                                 "172.17.0.1:47100\n")
    healthy.docker.exit_codes[:] = [90]
    fw = by_name(doctor.run_checks(healthy, "for-update"))["firewall"]
    assert fw["detail"] == ("the probe container stopped early (exit 90): ERROR: Firewall verification failed - "
                            "unable to reach the key proxy at 172.17.0.1:47100")
    assert "egress blocked" not in fw["detail"] and EXPECTED_RULE in fw["fix"]


def test_other_firewall_failures_keep_the_rebuild_fix(healthy):
    healthy.docker.outputs[0] = PROBE_OK.replace("host-blocked", "LEAK-HOST")
    fw = by_name(doctor.run_checks(healthy, "for-update"))["firewall"]
    assert fw["detail"] == "failed checks: egress blocked to the host (default gateway)"
    assert "Rebuild" in fw["fix"]


def test_proxy_rule_check(healthy):
    def rule():
        return by_name(doctor.run_checks(healthy, "for-update"))["proxy-rule"]
    healthy.docker.outputs[:] = []
    r = rule()                                    # FakeHost default: ufw prints nothing -> not active
    assert r["ok"] and "not active" in r["detail"]
    healthy.host.script(["ufw", "status"], 0, UFW_ON)
    r = rule()
    assert not r["ok"] and r["detail"].startswith("firewall rule for the key proxy is missing")
    assert EXPECTED_RULE in r["fix"]
    healthy.host.script(["ufw", "status"], 0, UFW_ON + UFW_RULE)
    r = rule()
    assert r["ok"] and r["detail"].startswith("firewall rule for the key proxy is in place")
    healthy.host.script(["ufw", "status"], 127, "", "not found: ufw")
    assert rule()["ok"]
    healthy.host.script(["ufw", "status"], 1, "", "need root")
    assert not rule()["ok"]
    assert ["ufw", "status"] in healthy.host.calls


def test_advisor_detected_from_init_event(healthy):
    assert by_name(doctor.run_checks(healthy, "full"))["advisor"]["ok"]
    info = json.loads((paths.config() / "doctor.json").read_text())
    assert info["advisor_available"] is True and info["claude_version"] == "2.1.301" and info["checked_at"]


def test_advisor_absent(healthy):
    healthy.docker.outputs[1] = session_log(skills=())
    found = by_name(doctor.run_checks(healthy, "full"))
    assert found["advisor"]["ok"] and "not available" in found["advisor"]["detail"]
    assert json.loads((paths.config() / "doctor.json").read_text())["advisor_available"] is False


def test_session_mounts_follow_doctor_json(tmp_path):
    skills = tmp_path / "skills"
    ai = {"advisor": {"on": True, "model": "m", "when": [], "instructions": ""}}
    step, proj = tmp_path / "step", tmp_path / "proj"
    step.mkdir(), proj.mkdir()

    def dsts():
        return [m.dst for m in claude.session_mounts(ai, step, proj, tmp_path / "t", skills)]

    assert not any("advisor" in d for d in dsts())                      # folder missing
    assert claude.advisor_note(ai, skills)
    (skills / "advisor").mkdir(parents=True)
    assert sum("advisor" in d for d in dsts()) == 2 and claude.advisor_note(ai, skills) == ""
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "doctor.json").write_text('{"advisor_available": false}')
    assert not any("advisor" in d for d in dsts())                      # doctor says unavailable
    assert "carry on without it" in claude.advisor_note(ai, skills)
    assert claude.advisor_note({}, skills) == ""
    (paths.config() / "doctor.json").write_text('{"advisor_available": true}')
    assert sum("advisor" in d for d in dsts()) == 2


@pytest.mark.parametrize("free_gb,docker_gb,ok,word", [
    (50, 50, True, ""), (10, 50, True, "getting low"), (50, 12, True, "getting low"),
    (4, 50, False, ""), (50, 4, False, "")])
def test_disk_thresholds(healthy, monkeypatch, free_gb, docker_gb, ok, word):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda p: Usage(10**12, 0, int(free_gb * doctor.GB)))
    healthy.host.script(["df"], 0, f"Avail\n{int(docker_gb * doctor.GB)}\n")
    check = by_name(doctor.run_checks(healthy, "quick"))["disk"]
    assert check["ok"] is ok and word in check["detail"]


def test_wrong_modes_reported(healthy, phoenix_env):
    home = phoenix_env["home"]
    (home / "secrets").chmod(0o755)
    (home / "keys" / "demo.toml").write_text("A='b'\n")
    (home / "keys" / "demo.toml").chmod(0o644)
    check = by_name(doctor.run_checks(healthy, "quick"))["home"]
    assert not check["ok"] and "secrets/ has mode 0755" in check["detail"] and "demo.toml" in check["detail"]
    assert "sk-secret-value" not in json.dumps(check)


def test_stale_hold_is_a_problem(healthy, phoenix_env):
    update = phoenix_env["home"] / "update"
    update.mkdir()
    hold = update / "hold"
    hold.write_text("{}")
    old = hold.stat().st_mtime - 4 * 3600
    os.utime(hold, (old, old))
    check = by_name(doctor.run_checks(healthy, "full"))["updater"]
    assert not check["ok"] and "stale" in check["detail"]


def test_json_output_shape(fake_ops, capsys):
    assert main(["doctor", "--for-update", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert all(set(c) == {"name", "ok", "detail", "fix"} for c in data["checks"])


def test_plain_output_counts_problems(fake_ops, capsys):
    fake_ops.host.script(["systemctl", "is-active"], 3, "inactive\ninactive\n")
    assert main(["doctor", "--quick"]) == 1
    out = capsys.readouterr().out
    assert "PROBLEM services" in out and "Fix:" in out and "1 problem." in out


def test_project_links_check_is_about_vs_code_only(healthy, phoenix_env):
    host = healthy.host
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    host.script(["systemctl", "is-active"], rc=3)          # no chat service anywhere: not a problem any more
    check = by_name(doctor.run_checks(healthy, "full"))["project-links"]
    assert check["ok"] and "chat" not in (check["detail"] + check["fix"]).lower()


def test_memory_files_check_lists_projects_and_the_fix(healthy, phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    (folder / "CLAUDE.md").write_text("# demo\n")
    check = by_name(doctor.run_checks(healthy, "full"))["memory-files"]
    assert not check["ok"] and "demo: " in check["detail"] and "notes/NOW.md" in check["detail"]
    assert "phoenix project check-files --all" in check["fix"]
    from phoenix9 import project_removal
    project_removal.add_memory_files(folder, "demo", "")
    assert by_name(doctor.run_checks(healthy, "full"))["memory-files"]["ok"]


def test_reference_check_warns_but_never_fails(healthy, phoenix_env):
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    ref = phoenix_env["projects"] / "demo" / "notes" / "reference"
    ref.mkdir(parents=True)
    (ref / "a.css").write_text("a{}")
    check = by_name(doctor.run_checks(healthy, "full"))["reference"]
    assert check["ok"] and "within the limits" in check["detail"]
    from phoenix9 import reference
    for i in range(reference.MAX_FILES + 1):
        (ref / f"f{i}.txt").write_text("x")
    check = by_name(doctor.run_checks(healthy, "full"))["reference"]
    assert check["ok"] and check["detail"].startswith("Warning:") and "demo" in check["detail"]
    assert "phoenix reference remove" in check["fix"]


def test_api_check_reads_the_tag_inside_the_api_reply(adapters, monkeypatch):
    """The real /api/health reply is {"ok": true, "data": {..., "tag"}}; the for-update check must find the tag there."""
    adapters.http.script("GET", "http://127.0.0.1:8095/api/health", 200,
                         body=b'{"ok": true, "data": {"ok": true, "tag": "v9.1"}}')
    monkeypatch.setattr(doctor, "installed_tags", lambda ctx: ["v9.1"])
    ok, detail, _ = doctor.check_api(doctor.Context(adapters, "for-update"))
    assert ok and "API runs v9.1" in detail


def agent_check(a, name):
    return by_name(doctor.run_checks(a, "full"))[name]


def test_agent_checks_pass_and_are_in_full_mode(healthy):
    names = ("agent-unit", "agent-session", "agent-socket", "agent-transcript", "agent-folder")
    assert all(n in doctor.CHECKS_BY_MODE["full"] for n in names)
    assert all(agent_check(healthy, n)["ok"] for n in names)


def test_agent_unit_inactive_fails_with_fix(healthy):
    healthy.host.script(["systemctl", "is-active", "claude-rc@home"], 3, "inactive\n")
    c = agent_check(healthy, "agent-unit")
    assert not c["ok"] and "inactive" in c["detail"] and "systemctl start" in c["fix"]


def test_agent_session_missing_fails_with_fix(healthy):
    healthy.host.pids.clear()
    c = agent_check(healthy, "agent-session")
    assert not c["ok"] and c["fix"]


@pytest.mark.parametrize("path,mode,uid,word", [
    ("/tmp/cc-socks-0", 0o755, 0, "0755"), (AGENT_SOCK, 0o666, 0, "0666"), (AGENT_SOCK, 0o600, 1000, "root")])
def test_agent_socket_wrong_mode_or_owner_fails(healthy, path, mode, uid, word):
    healthy.host.stats[path] = {"mode": mode, "uid": uid}
    c = agent_check(healthy, "agent-socket")
    assert not c["ok"] and word in c["detail"] and "chmod" in c["fix"]


def test_agent_socket_without_session_fails(healthy):
    healthy.host.pids.clear()
    assert not agent_check(healthy, "agent-socket")["ok"]


def test_agent_transcript_parse_rate(healthy):
    bad = healthy.host.files[AGENT_TRANSCRIPT] + "not json\n" * 5
    healthy.host.files[AGENT_TRANSCRIPT] = bad
    c = agent_check(healthy, "agent-transcript")
    assert not c["ok"] and "unknown" in c["detail"] and c["fix"]
    healthy.host.files[AGENT_TRANSCRIPT] = healthy.host.files[AGENT_TRANSCRIPT].replace("not json\n", "", 4)
    assert agent_check(healthy, "agent-transcript")["ok"]    # 1 of 21 lines is under 5 %


@pytest.mark.parametrize("missing", ["CLAUDE.md", ".claude/settings.json"])
def test_agent_folder_missing_files_fail(healthy, missing):
    del healthy.host.files[f"{AGENT_FOLDER}/{missing}"]
    c = agent_check(healthy, "agent-folder")
    assert not c["ok"] and missing in c["detail"] and c["fix"]


def test_service_home_reads_each_running_service_environment(healthy):
    check = by_name(doctor.run_checks(healthy, "quick"))["service-home"]
    assert check["ok"] and "HOME" in check["detail"]
    assert ["systemctl", "show", "-p", "MainPID", "--value", "phoenix-runner"] in healthy.host.calls
    assert "service-home" in doctor.CHECKS_BY_MODE["full"]


def test_service_home_missing_names_the_service_and_the_fix(healthy):
    healthy.host.files["/proc/101/environ"] = "PATH=/usr/bin\0"
    check = by_name(doctor.run_checks(healthy, "quick"))["service-home"]
    assert not check["ok"] and "phoenix-api has no HOME" in check["detail"]
    assert "phoenix-runner" not in check["detail"]
    assert "Environment=HOME=/root" in check["fix"] and "daemon-reload" in check["fix"]


def test_service_home_of_a_stopped_service_uses_its_unit_settings(healthy):
    healthy.host.script(["systemctl", "show", "-p", "MainPID", "--value", "phoenix-api"], 0, "0\n")
    healthy.host.script(["systemctl", "show", "-p", "Environment", "--value", "phoenix-api"], 0,
                        "PHOENIX_HOME=/var/lib/phoenix9 PYTHONUNBUFFERED=1\n")
    check = by_name(doctor.run_checks(healthy, "quick"))["service-home"]
    assert not check["ok"] and "phoenix-api has no HOME" in check["detail"]
    healthy.host.script(["systemctl", "show", "-p", "Environment", "--value", "phoenix-api"], 0,
                        "PHOENIX_HOME=/var/lib/phoenix9 HOME=/root\n")
    assert by_name(doctor.run_checks(healthy, "quick"))["service-home"]["ok"]


def test_service_home_unreadable_environment_is_a_problem(healthy):
    del healthy.host.files["/proc/101/environ"]
    check = by_name(doctor.run_checks(healthy, "quick"))["service-home"]
    assert not check["ok"] and "could not read phoenix-api's environment" in check["detail"]


@pytest.mark.parametrize("content", [None, "", "\n\n"])
def test_agent_transcript_missing_or_empty_is_not_a_pass(healthy, content):
    """A transcript that is not there (wrong folder rule) or has nothing in it must not read as healthy."""
    if content is None:
        del healthy.host.files[AGENT_TRANSCRIPT]
    else:
        healthy.host.files[AGENT_TRANSCRIPT] = content
    c = agent_check(healthy, "agent-transcript")
    assert not c["ok"] and AGENT_TRANSCRIPT in c["detail"] and c["fix"]


# ---- the program in front of the dashboard runs as an allowed uid ----

def test_upstream_check_passes_when_cloudflared_runs_as_root(healthy):
    healthy.host.programs = {"cloudflared": [0], "code-server": [0]}
    c = by_name(doctor.run_checks(healthy, "full"))["upstream"]
    assert c["ok"] and "cloudflared runs as uid 0" in c["detail"] and "code-server runs as uid 0" in c["detail"]
    assert "upstream" in doctor.CHECKS_BY_MODE["quick"] and "upstream" in doctor.CHECKS_BY_MODE["full"]


def test_upstream_check_fails_when_cloudflared_runs_as_another_user(healthy):
    healthy.host.programs = {"cloudflared": [997]}
    c = by_name(doctor.run_checks(healthy, "full"))["upstream"]
    assert not c["ok"] and "cloudflared runs as uid 997" in c["detail"] and "not allowed" in c["detail"]
    assert "access.peer_uids" in c["fix"]
    (paths.home() / "config").mkdir(parents=True, exist_ok=True)
    (paths.home() / "config" / "global.toml").write_text("[access]\npeer_uids = [0, 997]\n")
    c = by_name(doctor.run_checks(healthy, "full"))["upstream"]
    assert c["ok"] and "997" in c["detail"]


def test_upstream_check_with_nothing_running_says_so(healthy):
    healthy.host.programs = {}
    c = by_name(doctor.run_checks(healthy, "full"))["upstream"]
    assert c["ok"] and "cloudflared is not running" in c["detail"]


def test_upstream_check_reports_a_wrong_peer_uids_setting(healthy):
    healthy.host.programs = {"cloudflared": [0]}
    (paths.home() / "config").mkdir(parents=True, exist_ok=True)
    (paths.home() / "config" / "global.toml").write_text('[access]\npeer_uids = "root"\n')
    c = by_name(doctor.run_checks(healthy, "full"))["upstream"]
    assert not c["ok"] and "peer_uids" in c["detail"] and c["fix"]


def test_host_program_uids_reads_proc(tmp_path):
    """The real host finds processes by program name (argv[0], or argv[1] for an interpreter) and their uid."""
    from phoenix9 import adapters as real
    for pid, argv, uid in ((10, ["/usr/bin/cloudflared", "tunnel"], 0),
                           (11, ["/usr/lib/code-server/lib/node", "/usr/lib/code-server"], 0),
                           (12, ["/usr/bin/cloudflared"], 997),
                           (13, ["/bin/bash", "-c", "cloudflared"], 1000)):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "status").write_text(f"Name:\tx\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    (tmp_path / "self").mkdir()
    host = real.Host()
    assert host.program_uids("cloudflared", proc=str(tmp_path)) == [0, 997]
    assert host.program_uids("code-server", proc=str(tmp_path)) == [0]
    assert host.program_uids("nginx", proc=str(tmp_path)) == []


def test_project_chats_check_lists_units_and_never_fails_for_no_chat(healthy, phoenix_env):
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    healthy.host.script(["systemctl", "is-active"], rc=3, out="inactive\n")
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert check["ok"] and "demo: none" in check["detail"]


def test_project_chats_check_warns_for_failed_unit_with_the_fix(healthy, phoenix_env):
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    healthy.host.script(["systemctl", "is-active"], rc=3, out="failed\n")
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert not check["ok"] and "phoenix chat forget demo --yes" in check["fix"]
    assert "press Chat to try again; if it repeats: phoenix chat forget demo --yes" in check["fix"]


@pytest.mark.parametrize("state", ["asleep", "awake", "working"])
def test_project_chats_check_says_nothing_for_a_healthy_chat(healthy, phoenix_env, monkeypatch, state):
    from phoenix9 import projectchat
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    monkeypatch.setattr(projectchat, "state", lambda name, ad: {"state": state})
    healthy.host.script(["systemctl", "is-active"], 0, "active\n")
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert check["ok"] and check["detail"] == f"demo: {state}" and not check["fix"]


def test_project_chats_check_reports_an_unreadable_chat_document(healthy, phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    (folder / "CLAUDE.md").write_text("# demo\n")
    (folder / ".phoenix").mkdir()
    (folder / ".phoenix" / "chat.md").write_bytes(b"\xff\xfe not text")
    healthy.host.script(["systemctl", "is-active"], rc=3, out="inactive\n")
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert not check["ok"] and "demo: the chat document is unreadable" in check["detail"]
    assert "phoenix chat forget demo --yes" in check["fix"]


def test_project_chats_check_warns_about_stray_chats_with_the_tidy_fix(healthy, phoenix_env):
    (phoenix_env["projects"] / "demo" / "CLAUDE.md").write_text("# demo\n")
    healthy.host.script(["systemctl", "is-active"], rc=3, out="inactive\n")
    healthy.host.script(["systemctl", "list-units"], 0, "claude-rc-chat@demo.service loaded active running x\n"
                                                         "claude-rc-chat@gone.service loaded active running x\n")
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert check["ok"] and "Warning: chats running for projects that are not listed: gone." in check["detail"]
    assert "`phoenix chat tidy --yes`" in check["detail"] and "demo," not in check["detail"]


@pytest.mark.parametrize("breaker, words", [
    (lambda h: h.stats.pop(str(LAUNCHER())), "is missing"),
    (lambda h: h.stats.update({str(LAUNCHER()): {"mode": 0o644, "uid": 0}}), "is not executable"),
    (lambda h: h.script(["systemctl", "cat", doctor.CHAT_UNIT_FILE], 0,
                        "[Service]\nExecStart=/usr/bin/claude remote-control\n"), "does not start"),
    (lambda h: h.script(["systemctl", "cat", doctor.CHAT_UNIT_FILE], 1, "", "No files found"), "does not start"),
])
def test_project_chats_check_reports_a_broken_launcher(healthy, phoenix_env, breaker, words):
    healthy.host.script(["systemctl", "is-active"], rc=3, out="inactive\n")
    breaker(healthy.host)
    check = by_name(doctor.run_checks(healthy, "full"))["project-chats"]
    assert not check["ok"] and words in check["detail"] and "chat-launch.sh" in check["detail"]
    assert "`phoenix update` or re-run the installer" in check["fix"]
