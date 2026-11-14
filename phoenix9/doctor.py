"""The health checks behind `phoenix doctor`: each check is a small function and one failing check never stops the others."""
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import access, agentnext, agentaccess, agentlink, atomic, claude, docker, hold, hostfw, paths, project, proxy, scrub, settings
from phoenix9 import transcript
from phoenix9.library import read_toml

MODES = ("full", "for-update", "quick")
GB = 1024 ** 3
DISK_FAIL_GB, DISK_WARN_GB = 5, 15
STALE_HOLD_S = 3 * 3600
DEFAULT_API_PORT = 8095
UNKNOWN_WARN_RATE = 0.05
SOCKET_FOLDER_MODE, SOCKET_MODE = 0o700, 0o600
SERVICES = ("phoenix-api", "phoenix-runner")
HOME_FOLDERS = ("config", "secrets", "keys", "runs", "logs")
PROBE_PROFILE = "python-script"
CLAUDE_MODEL = "haiku"
CLAUDE_MINUTES = 5
CHECKS_BY_MODE = {
    "quick": ("services", "service-home", "api", "origins", "upstream", "home", "secrets", "disk",
              "agentkit-service", "agentkit-key", "agentkit-spend"),
    "for-update": ("services", "api", "home", "images", "proxy-rule", "firewall"),
    "full": ("python", "library", "services", "service-home", "api", "origins", "upstream", "home", "secrets", "images", "proxy-rule", "firewall",
             "claude", "advisor", "disk", "updater", "project-links", "memory-files", "reference",
             "agent-unit", "agent-session", "agent-socket", "agent-transcript", "agent-folder", "agent-pack", "agent-helpers", "agent-rules", "project-chats", "access",
             "agentkit-service", "agentkit-key", "agentkit-spend"),
}


class Context:
    """What the checks share: the adapters, the mode and what the Claude session found."""

    def __init__(self, adapters, mode: str):
        """Remember the adapters and mode; the Claude check fills in `claude_info`."""
        self.ad = adapters
        self.mode = mode
        self.claude_info: dict | None = None
        self.agent_found: dict | None = None


def _result(ok: bool, detail: str, fix: str = "") -> tuple[bool, str, str]:
    return ok, detail, "" if ok else fix


def _profile_image(name: str) -> str:
    return settings.profile_image(paths.library(), name)


def projects_profiles() -> list[str]:
    """Profile names used by the existing projects (sorted, no duplicates)."""
    root = paths.projects()
    found = set()
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if folder.is_dir() and not folder.name.startswith("."):
            name = project.profile_of(folder)
            if name:
                found.add(name)
    return sorted(found)


# ------------------------------------------------------------- the checks
def check_python(ctx):
    """Python is new enough."""
    ok = sys.version_info >= (3, 12)
    return _result(ok, f"Python {sys.version.split()[0]}", "Install Python 3.12 or newer.")


def check_library(ctx):
    """The step library loads without problems."""
    from phoenix9.ops import common
    lib = common.library()
    return _result(not lib.problems, f"{len(lib.steps)} steps loaded, {len(lib.problems)} problems",
                   "Run `phoenix library check` and fix the problems it lists.")


def check_services(ctx):
    """phoenix-api and phoenix-runner are running."""
    rc, out, _ = ctx.ad.host.run(["systemctl", "is-active", *SERVICES])
    states = out.split()
    bad = [f"{n} is {states[i] if i < len(states) else 'unknown'}" for i, n in enumerate(SERVICES)
           if i >= len(states) or states[i] != "active"]
    return _result(not bad, "phoenix-api and phoenix-runner are active" if not bad else "; ".join(bad),
                   "Start them with `systemctl start phoenix-api phoenix-runner`, then read `journalctl -u phoenix-api`.")


def _service_env(ctx, name: str) -> dict | None:
    """The environment of a running service (/proc/<MainPID>/environ), or its unit's Environment= when stopped;
    None when it cannot be read."""
    rc, out, _ = ctx.ad.host.run(["systemctl", "show", "-p", "MainPID", "--value", name])
    pid = out.strip()
    if rc == 0 and pid.isdigit() and pid != "0":
        try:
            text = ctx.ad.host.read_text(f"/proc/{pid}/environ")
        except (OSError, UnicodeDecodeError):
            return None
        pairs = text.split("\0")
    else:
        rc, out, _ = ctx.ad.host.run(["systemctl", "show", "-p", "Environment", "--value", name])
        if rc != 0:
            return None
        pairs = out.split()
    return dict(p.split("=", 1) for p in pairs if "=" in p)


def check_service_home(ctx):
    """phoenix-api and phoenix-runner run with HOME set, so git and gh can read root's GitHub login."""
    problems = []
    for name in SERVICES:
        env = _service_env(ctx, name)
        if env is None:
            problems.append(f"could not read {name}'s environment")
        elif not env.get("HOME"):
            problems.append(f"{name} has no HOME")
    if not problems:
        return _result(True, "services: HOME set for phoenix-api and phoenix-runner")
    return _result(False, "services: HOME not set: " + "; ".join(problems) +
                   " (git and gh cannot find the GitHub login, so pushes fail)",
                   "Add `Environment=HOME=/root` to the unit in /etc/systemd/system (deploy/install.sh or "
                   "`phoenix update install` copies the fixed units), then run `systemctl daemon-reload && "
                   "systemctl restart phoenix-api phoenix-runner`. Run `phoenix doctor` as root.")


def api_port() -> int:
    """The API port from HOME/config/api.env (default 8095)."""
    try:
        text = (paths.config() / "api.env").read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_API_PORT
    m = re.search(r"^\s*PHOENIX_API_PORT\s*=\s*['\"]?(\d+)", text, re.M)
    return int(m.group(1)) if m else DEFAULT_API_PORT


def health_fields(body: bytes) -> dict:
    """The fields of an /api/health reply (the API wraps them in {"ok", "data"}; older fakes send them bare)."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        return {}
    return data["data"] if isinstance(data.get("data"), dict) else data


def installed_tags(ctx) -> list[str]:
    """The release tags pointing at the installed copy's commit."""
    inst = paths.install()
    try:
        done = ctx.ad.git.run_git(inst, "tag", "--points-at", "HEAD", check=False, timeout=15)
    except Exception:
        return []
    names = done.stdout.decode(errors="replace").split() if done.returncode == 0 else []
    return [n for n in names if re.fullmatch(r"v9\.\d+", n)]


def check_api(ctx):
    """The API answers /api/health (and, for an update, runs the installed release)."""
    url = f"http://127.0.0.1:{api_port()}/api/health"
    fix = "Restart the API with `phoenix service restart api --yes` and read `journalctl -u phoenix-api`."
    try:
        status, _, body = ctx.ad.http.request("GET", url, timeout=10)
    except Exception as err:
        return _result(False, f"{url} did not answer ({type(err).__name__})", fix)
    if status != 200:
        return _result(False, f"{url} answered {status}", fix)
    if ctx.mode != "for-update":
        return _result(True, f"{url} answered 200")
    try:
        running = str(health_fields(body).get("tag") or "")
    except ValueError:
        running = ""
    tags = installed_tags(ctx)
    if not tags:
        return _result(False, "the installed copy is not at a release tag", "Check the install folder with `git tag --points-at HEAD`.")
    ok = running in tags
    return _result(ok, f"API runs {running or 'no release'}; installed is {', '.join(tags)}",
                   "The API is still running old code; restart it with `phoenix service restart api --yes`.")


def check_origins(ctx):
    """The page origins the running API allows (a digest in /api/health) match the allowed_origins setting."""
    from phoenix9 import addresses
    url = f"http://127.0.0.1:{api_port()}/api/health"
    want = addresses.read()["allowed_origins"]
    fix = "Restart the API with `phoenix service restart api --yes` so it picks up the setting."
    try:
        status, _, body = ctx.ad.http.request("GET", url, timeout=10)
        fields = health_fields(body) if status == 200 else {}
    except Exception:  # noqa: BLE001 - the api check reports why the API did not answer
        fields = {}
    digest, served = fields.get("origins_digest"), fields.get("origins")
    if isinstance(digest, str) and digest:
        ok = digest == addresses.origins_digest(want)
        return _result(ok, f"the running API allows {', '.join(want)}" if ok else
                       f"the running API allows different origins; the setting says {', '.join(want)}", fix)
    if not isinstance(served, list):     # an API from before the digest sent the list itself
        return _result(False, "the running API did not say which origins it allows (old version or not answering)", fix)
    ok = sorted(served) == sorted(want)
    detail = (f"the running API allows {', '.join(served)}" if ok else
              f"the running API allows {', '.join(served) or 'nothing'}; the setting says {', '.join(want)}")
    return _result(ok, detail, fix)


UPSTREAM_PROGRAMS = ("cloudflared", "code-server")   # what sits in front of the dashboard and connects to the API


def check_upstream(ctx):
    """The programs in front of the dashboard (cloudflared, code-server) run as a uid the API answers."""
    allowed = access.peer_uids()
    problem = access.peer_uids_problem()
    agent_problem = agentaccess.uid_problem(allowed)
    if agent_problem:
        return _result(False, agent_problem, f"Set agent_next.uid in {paths.home()}/config/global.toml to the agent's "
                       "own user (not 0, and not a uid in access.peer_uids).")
    found = {name: ctx.ad.host.program_uids(name) for name in UPSTREAM_PROGRAMS}
    parts, bad = [], []
    for name, uids in found.items():
        for uid in uids:
            parts.append(f"{name} runs as uid {uid}")
            if uid not in allowed:
                bad.append(f"{name} (uid {uid})")
    allowed_text = ", ".join(str(u) for u in allowed)
    setting = f"{paths.home()}/config/global.toml"
    if problem:
        return _result(False, problem, f"Fix access.peer_uids in {setting}, e.g. peer_uids = [0].")
    if bad:
        return _result(False, f"{'; '.join(parts)}: {', '.join(bad)} not allowed, so the dashboard is refused "
                       f"(the API allows uid {allowed_text})",
                       f"Run it as root, or add its uid to access.peer_uids in {setting}.")
    if not parts:
        return _result(True, f"cloudflared is not running (nothing in front of the dashboard to check; "
                       f"the API allows uid {allowed_text})")
    return _result(True, f"{'; '.join(parts)}; the API allows uid {allowed_text}")


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def check_home(ctx):
    """The HOME layout exists and secrets and keys are owner-only."""
    home = paths.home()
    problems = [f"{n}/ is missing" for n in HOME_FOLDERS if not (home / n).is_dir()]
    for name in ("secrets", "keys"):
        folder = home / name
        if not folder.is_dir():
            continue
        if _mode(folder) != 0o700:
            problems.append(f"{name}/ has mode {_mode(folder):04o}, expected 0700")
        for f in sorted(p for p in folder.iterdir() if p.is_file()):
            if _mode(f) != 0o600:
                problems.append(f"{name}/{f.name} has mode {_mode(f):04o}, expected 0600")
    return _result(not problems, "layout and modes are right" if not problems else "; ".join(problems),
                   "Create the missing folders and run `chmod 700 secrets keys; chmod 600 secrets/* keys/*` inside Phoenix home.")


def check_secrets(ctx):
    """claude.env is there (names only; values are never read here)."""
    secrets = paths.secrets()
    if not (secrets / "claude.env").is_file():
        return _result(False, "claude.env is missing", "Put the Claude token in Global settings (or secrets/claude.env).")
    github = "github connected" if (secrets / "github.env").is_file() else "github not connected"
    return _result(True, f"claude.env present; {github}")


def _cpus_note(ctx) -> str:
    """One plain sentence on how many cores check containers get (or why the setting is refused)."""
    try:
        return f"test runs may use {docker._cpu_text(docker.check_cpus(ctx.ad.docker))} cores"
    except ValueError as err:
        return f"Warning: {err}"


def library_profiles() -> list[str]:
    """Every profile name in the library (folders under profiles/ with a profile.toml), sorted."""
    root = paths.library() / "profiles"
    found = root.iterdir() if root.is_dir() else []
    return sorted(p.name for p in found if (p / "profile.toml").is_file() and not p.name.startswith("."))


def _missing_line(name: str, tag: str) -> str:
    """One plain line for a profile whose image is not built, with the command that builds it."""
    what = f"{name} ({tag})" if tag else f"{name} (its profile names no image)"
    return f"{what}: build it with `phoenix images build --profile {name}`"


def check_images(ctx):
    """Every profile image a project uses has been built (fails if not); other profiles' missing images are a warning.
    Also says how many cores test runs may use."""
    used = projects_profiles()
    missing_used, missing_other = [], []
    for name in sorted(set(used) | set(library_profiles())):
        tag = _profile_image(name)
        if not tag or not ctx.ad.docker.image_exists(tag):
            (missing_used if name in used else missing_other).append(_missing_line(name, tag))
    if missing_used:
        return _result(False, "image missing for a profile your projects use: " + "; ".join(missing_used)
                       + "".join(f"; also not built: {line}" for line in missing_other),
                       "Build them with `phoenix images build --profile <name>` (or `--all`).")
    detail = (f"{len(used)} profile images present; " if used else "no projects yet; ") + _cpus_note(ctx)
    if missing_other:
        detail += "\nWarning: these profiles' images are not built: " + "; ".join(missing_other)
    return _result(True, detail)


def _probe_image(ctx) -> str:
    """The python-script profile's image tag if it exists, else ''."""
    tag = _profile_image(PROBE_PROFILE)
    return tag if tag and ctx.ad.docker.image_exists(tag) else ""


def proxy_rule(ctx) -> tuple[dict, tuple[int, int], str]:
    """(bridge info, proxy port range, the exact ufw command) for the key proxy rule; install.sh adds the same."""
    info = ctx.ad.docker.bridge_info()
    ports = settings.proxy_ports()
    return info, ports, hostfw.ufw_rule_text(info["interface"], info["subnet"], info["gateway"], ports)


def check_proxy_rule(ctx):
    """When ufw is on, it has the one rule that lets step containers reach the key proxy's port range."""
    rc, out, err = ctx.ad.host.run(["ufw", "status"])
    if rc == 127:
        return _result(True, "firewall rule for the key proxy: not needed (ufw is not installed)")
    if rc != 0:
        return _result(False, f"firewall rule for the key proxy: could not read `ufw status` (exit {rc})",
                       "Run `phoenix doctor` as root.")
    if not hostfw.ufw_active(out):
        return _result(True, "firewall rule for the key proxy: not needed (ufw is not active)")
    info, ports, rule = proxy_rule(ctx)
    if hostfw.rule_present(out, info["interface"], info["subnet"], info["gateway"], ports):
        return _result(True, f"firewall rule for the key proxy is in place ({info['subnet']} -> "
                             f"{info['gateway']} ports {ports[0]}-{ports[1]})")
    return _result(False, "firewall rule for the key proxy is missing: ufw is on, so step containers "
                          f"cannot reach the proxy on {info['gateway']} ports {ports[0]}-{ports[1]}",
                   f"Add it as root: {rule}   (or run deploy/install.sh --firewall-only)")


def check_firewall(ctx):
    """The container firewall blocks what it should and lets the key proxy through."""
    image = _probe_image(ctx)
    if not image:
        return _result(False, "no step image to test with", "Build the images with `phoenix images build --all`.")
    spec = proxy.ProxySpec("doctor", "https://api.anthropic.com", "Authorization", "Bearer {key}", ())
    gateway = ctx.ad.docker.bridge_gateway()
    log = paths.home() / "cache" / "doctor" / "proxy.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = ctx.ad.proxy.start(spec, "doctor-dummy-key", log_path=log, step="doctor", bind=gateway)
    try:
        failures = docker.probe_firewall(ctx.ad.docker, image, proxy=(gateway, handle.port))
    finally:
        handle.stop()
    if not failures:
        return _result(True, "firewall probe passed")
    if len(failures) == 1 and failures[0].startswith(docker.STOPPED_EARLY):
        detail = failures[0]
    else:
        detail = "failed checks: " + "; ".join(failures)
    if any("key proxy" in f for f in failures):
        _, _, rule = proxy_rule(ctx)
        fix = (f"Step containers cannot reach the key proxy. If ufw is on, add this rule as root: {rule}   "
               "(or run deploy/install.sh --firewall-only)")
    else:
        fix = "Rebuild the images with `phoenix images build --all` and check Docker's network rules."
    return _result(False, detail[:600], fix + " Full probe output: HOME/cache/doctor/firewall-probe.txt")


def _stream_info(log: Path) -> tuple[bool, str]:
    """(advisor listed in the session's init event, claude version) from a stream-json log."""
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return False, ""
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
            listed = [str(x).lstrip("/") for x in [*(event.get("slash_commands") or []), *(event.get("skills") or [])]]
            return "advisor" in listed, str(event.get("claude_code_version") or "")
    return False, ""


def check_claude(ctx):
    """One tiny Claude session in a step container works (so the token is valid)."""
    image = _probe_image(ctx)
    if not image:
        return _result(False, "no step image to run Claude in", "Build the images with `phoenix images build --all`.")
    work = paths.home() / "cache" / "doctor" / "claude"
    (work / "workspace").mkdir(parents=True, exist_ok=True)
    prompt = work / "prompt.md"
    prompt.write_text("Reply with OK\n", encoding="utf-8")
    data, _ = read_toml(paths.library() / "profiles" / PROBE_PROFILE / "profile.toml", PROBE_PROFILE)
    domains = docker.write_domains_file("doctor", (data or {}).get("allowed_domains") or ())
    cmd = claude.build_command({"model": CLAUDE_MODEL, "max_turns": 1}, docker.PROMPT_MOUNT, "/workspace")
    rc, log = docker.run_claude_container(ctx.ad.docker, "doctor", "doctor", 0, 0, "claude", image,
                                          work / "workspace", prompt, cmd, CLAUDE_MINUTES, domains_file=domains)
    result = claude.parse(log, rc)
    advisor, version = _stream_info(log)
    ok = rc == 0 and result.kind == "ok"
    if ok:
        ctx.claude_info = {"advisor_available": advisor, "claude_version": version}
    return _result(ok, "a test session ran and answered" if ok else f"the test session ended as {result.kind} (exit {rc})",
                   "Renew the Claude token in Global settings, then run `phoenix doctor` again.")


def check_advisor(ctx):
    """Records in HOME/config/doctor.json whether this Claude has the advisor skill."""
    info = ctx.claude_info
    if info is None:
        return _result(False, "not checked: the Claude test session did not succeed", "Fix the Claude check first.")
    atomic.write_json(paths.config() / "doctor.json", {
        **info, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    detail = ("the advisor is available" if info["advisor_available"]
              else "the advisor is not available; sessions carry on without it")
    return _result(True, f"{detail} (Claude {info['claude_version'] or 'version unknown'})")


def _free_gb_home() -> float:
    return shutil.disk_usage(paths.home()).free / GB


def _free_gb_docker(ctx) -> float | None:
    rc, out, _ = ctx.ad.host.run(["df", "-B1", "--output=avail", "/var/lib/docker"])
    nums = re.findall(r"^\s*(\d+)\s*$", out, re.M)
    return int(nums[-1]) / GB if rc == 0 and nums else None


def check_disk(ctx):
    """Free space on Phoenix home and on the Docker data folder (fail under 5 GB, warn under 15 GB)."""
    try:
        spaces = {"Phoenix home": _free_gb_home()}
    except OSError:
        return _result(False, "cannot measure the Phoenix home disk", "Check that Phoenix home exists.")
    spaces["Docker data"] = _free_gb_docker(ctx)
    unknown = [k for k, v in spaces.items() if v is None]
    known = {k: v for k, v in spaces.items() if v is not None}
    text = ", ".join(f"{k} {v:.1f} GB free" for k, v in known.items())
    if unknown:
        text += "; could not measure " + ", ".join(unknown)
    low = [k for k, v in known.items() if v < DISK_FAIL_GB]
    if low or unknown:
        return _result(False, text, "Free some disk space (`docker system prune`, old runs) or measure it by hand.")
    if any(v < DISK_WARN_GB for v in known.values()):
        text = "getting low: " + text
    return _result(True, text)


def check_updater(ctx):
    """The updater's status file is readable, no hold is stuck, and its systemd unit is installed."""
    problems = []
    status = paths.home() / "update" / "status.json"
    if status.exists():
        try:
            atomic.read_json(status)
        except (OSError, ValueError):
            problems.append("update/status.json cannot be read")
    held = paths.home() / "update" / "hold"
    if held.exists() and not hold.lock_held() and time.time() - held.stat().st_mtime > STALE_HOLD_S:
        problems.append("a stale update hold file is left over (older than 3 hours, no update running)")
    rc, _, _ = ctx.ad.host.run(["systemctl", "cat", "phoenix9-update.service"])
    if rc != 0:
        problems.append("phoenix9-update.service is not installed")
    return _result(not problems, "updater files and unit are fine" if not problems else "; ".join(problems),
                   "Delete the stale hold file, or reinstall the unit with install.sh.")


def check_project_links(ctx):
    """Every project has a VS Code link."""
    problems = []
    for name in project.project_names():
        vscode = project.vscode_link(name)
        if vscode["url"] is None and "does not exist" in (vscode["reason"] or ""):
            problems.append(f"{name}: VS Code link missing (folder not found)")
    return _result(not problems, "every project has its VS Code link" if not problems else "; ".join(problems),
                   "Check the project's folder still exists under the projects folder.")


def check_memory_files(ctx):
    """Every project has its memory files."""
    from phoenix9 import project_removal
    lacking = {n: project_removal.missing_memory_files(n) for n in project.project_names()}
    problems = [f"{n}: {', '.join(m)}" for n, m in lacking.items() if m]
    return _result(not problems, "every project has its memory files" if not problems else "; ".join(problems),
                   "Run `phoenix project check-files --all` to add what is missing.")


def _reference_problems(name: str) -> list[str]:
    """What is outside the limits in one project's notes/reference folder, in plain words."""
    from phoenix9 import reference
    ref = reference.folder(name)
    if not ref.is_dir():
        return []
    files = [p for p in ref.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith(".")]
    big = [p.name for p in files if p.stat().st_size > reference.MAX_FILE]
    problems = [f"{name}: {n} is over {reference.MAX_FILE // (1024 * 1024)} MB" for n in big]
    if len(files) > reference.MAX_FILES:
        problems.append(f"{name}: {len(files)} files (at most {reference.MAX_FILES})")
    if sum(p.stat().st_size for p in files) > reference.MAX_TOTAL:
        problems.append(f"{name}: the files add up to more than {reference.MAX_TOTAL // (1024 * 1024)} MB")
    return problems


def check_reference(ctx):
    """Every project's notes/reference is within the limits (a warning only; it never fails the report)."""
    problems = []
    for name in project.project_names():
        try:
            problems += _reference_problems(name)
        except Exception:
            problems.append(f"{name}: the reference folder cannot be read")
    if not problems:
        return True, "every project's reference material is within the limits", ""
    fix = "Remove the extra or oversized files with `phoenix reference remove <project> <file>`; builds skip what is over the limits."
    return True, "Warning: " + "; ".join(problems) + ". Fix: " + fix, fix


def check_agent_unit(ctx):
    """The agent's systemd unit is active."""
    unit = settings.agent_settings()["unit"]
    rc, out, _ = ctx.ad.host.systemctl("is-active", unit)
    state = out.split()[0] if out.split() else "unknown"
    ok = rc == 0 and state == "active"
    detail = f"{unit} is {state}"
    if not ok:
        from phoenix9 import agentwatch
        if agentwatch.memory()["stopped"]:
            detail += ": stopped by someone, so the watchdog leaves it alone"
    return _result(ok, detail, f"Start it with `systemctl start {unit}`, then read `journalctl -u {unit}`.")


def check_agent_session(ctx):
    """The agent's chat session is found in Claude's session list."""
    found = agentlink.find(host=ctx.ad.host)
    ctx.agent_found = found
    return _result(found is not None, "the agent session is running" if found else "no agent session found",
                   "Restart the agent with `phoenix agent restart --yes`, or check its unit with `systemctl status claude-rc@home`.")


def check_agent_socket(ctx):
    """The inbox socket folder is private (0700) and the socket is root-only (0600)."""
    found = agentlink.find(host=ctx.ad.host)
    if not found:
        return _result(False, "no agent session, so no inbox socket to check", "Start the agent first (see the agent-session line).")
    sock = found["socket"]
    folder = sock.rsplit("/", 1)[0] or "/"
    problems = []
    for what, path, want in (("socket folder", folder, SOCKET_FOLDER_MODE), ("socket", sock, SOCKET_MODE)):
        st = ctx.ad.host.stat(path)
        if st is None:
            problems.append(f"the {what} {path} cannot be read")
            continue
        if st["mode"] != want:
            problems.append(f"the {what} {path} has mode {st['mode']:04o}, not {want:04o}")
        if what == "socket" and st.get("uid") != 0:
            problems.append(f"the socket {path} is not owned by root")
    return _result(not problems, "socket folder is 0700 and the socket is 0600, owned by root" if not problems
                   else "; ".join(problems),
                   f"Run `chmod 700 {folder}` and `chmod 600 {sock}` (as root), or restart the agent.")


def check_agent_transcript(ctx):
    """Few lines of the agent's transcript are unknown to the parser (warn above 5 %)."""
    found = agentlink.find(host=ctx.ad.host)
    if not found or not found["transcript"]:
        return _result(False, "no agent transcript to read", "Start the agent first (see the agent-session line).")
    path = found["transcript"]
    lines = [ln for ln in ctx.ad.host.read_lines(path) if ln.strip()]
    if not lines:
        what = "is empty" if ctx.ad.host.exists(path) else "was not found"
        return _result(False, f"the agent transcript {path} {what}",
                       "If the agent has only just started, send it a message and check again; otherwise Claude "
                       "Code may name its transcript folders differently now: update phoenix9/agentlink.py.")
    unknown = transcript.parse(lines)[1]
    rate = unknown / len(lines)
    text = f"{unknown} of {len(lines)} transcript lines are unknown ({rate:.0%})"
    return _result(rate <= UNKNOWN_WARN_RATE, text,
                   "Claude Code's transcript format may have changed: update phoenix9/transcript.py.")


def check_agent_folder(ctx):
    """The agent folder has CLAUDE.md and .claude/settings.json."""
    folder = settings.agent_settings()["folder"].rstrip("/")
    missing = [n for n in ("CLAUDE.md", ".claude/settings.json") if not ctx.ad.host.exists(f"{folder}/{n}")]
    return _result(not missing, f"{folder} has CLAUDE.md and .claude/settings.json" if not missing
                   else f"{folder} lacks " + " and ".join(missing),
                   f"Set the agent folder up again (copy the agent files into {folder}).")


def check_agent_pack(ctx):
    """The agent folder's knowledge pack carries the installed version line."""
    from phoenix9 import agentsync
    ok, detail = agentsync.pack_current(ctx.ad.host)
    return _result(ok, detail, "Run an update, or copy deploy/agent/skills/ into the agent folder's .claude/skills/.")


def check_agent_helpers(ctx):
    """The agent folder's helper files match the installed ones (a warning only; it never fails the report)."""
    from phoenix9 import agentsync
    ok, detail = agentsync.helpers_current(ctx.ad.host)
    fix = "Run an update, or copy deploy/agent/agents/ into the agent folder's .claude/agents/."
    if ok:
        return _result(True, detail)
    return True, f"Warning: {detail}. Fix: {fix}", fix


def check_agent_rules(ctx):
    """The agent's rules file equals the installed rules plus its kept local section."""
    from phoenix9 import agentsync
    ok, detail = agentsync.rules_current(ctx.ad.host)
    if ok and agentsync.pending_restart():
        return _result(True, "agent rules updated; restart when idle")
    return _result(ok, detail, "Run an update to rebuild the agent's rules file from deploy/agent/agent-rules.md.")


CHAT_UNIT_FILE = "claude-rc-chat@.service"


def _chat_launcher_problems(ctx) -> list[str]:
    """What is wrong with the installed chat launcher and the chat unit file that starts it ([] when fine)."""
    launcher = paths.install() / "deploy" / "chat-launch.sh"
    st = ctx.ad.host.stat(launcher)
    if st is None:
        problems = [f"the chat launcher {launcher} is missing"]
    elif not st["mode"] & 0o111:
        problems = [f"the chat launcher {launcher} is not executable"]
    else:
        problems = []
    rc, out, _ = ctx.ad.host.systemctl("cat", CHAT_UNIT_FILE)
    starts = [ln for ln in (out or "").splitlines() if ln.strip().startswith("ExecStart=")] if rc == 0 else []
    if not any(str(launcher) in ln for ln in starts):
        problems.append(f"the installed {CHAT_UNIT_FILE} does not start {launcher}")
    return problems


def check_project_chats(ctx):
    """Each project's chat: problems for a failed unit, an unreadable chat document or a broken launcher; a
    warning for chats running for projects that are not listed."""
    from phoenix9 import chat, projectchat
    lines, problems, fixes = [], [], []
    for name in project.project_names():
        _, reason = projectchat.read_chat_doc(name)
        if reason and reason != "no chat document":
            problems.append(f"{name}: the chat document is unreadable ({reason})")
            fixes.append(f"`phoenix chat forget {name} --yes`, then press Chat")
            continue
        lines.append(f"{name}: {projectchat.state(name, ctx.ad)['state']}")
        if chat.unit_state(ctx.ad.host, name) == "failed":
            problems.append(f"{name}: the chat unit failed")
            fixes.append(f"press Chat to try again; if it repeats: phoenix chat forget {name} --yes")
    launcher = _chat_launcher_problems(ctx)
    if launcher:
        problems += launcher
        fixes.append("`phoenix update` or re-run the installer")
    detail = "; ".join(lines) if lines else "no projects yet"
    if problems:
        detail += "\nProblem: " + "; ".join(problems)
    stray = chat.stray_units(ctx.ad.host)
    if stray:
        detail += ("\nWarning: chats running for projects that are not listed: " + ", ".join(stray)
                   + ". Fix: `phoenix chat tidy --yes`")
    return _result(not problems, detail, "; ".join(fixes))


def check_access(ctx):
    """The optional Cloudflare Access lock on the API (every route but /api/health): off, on, or half set up."""
    cfg = access.settings()
    if cfg["on"]:
        return _result(True, f"the dashboard needs a Cloudflare Access token from {cfg['team_domain']}")
    if cfg["team_domain"] or cfg["aud"]:
        missing = "aud" if cfg["team_domain"] else "team_domain"
        return _result(False, f"the Access lock is half set up: access.{missing} is missing, so it is off",
                       f"Add access.{missing} to {paths.home()}/config/global.toml, or remove the [access] table.")
    return _result(True, "the optional Cloudflare Access lock is off (the API still answers only allowed uids on this server)")


AGENTKIT_UNIT = "phoenix-agentkit"
NOT_SET_UP = "not set up yet"
SPEND_WORDS = {"plenty": (True, "plenty left this month"), "low": (True, "getting low this month"),
               "used_up": (False, "used up this month")}


def _agentkit_status(ctx) -> tuple[dict | None, str]:
    """(the agent's /status answer, "") or (None, plain reason); reason is NOT_SET_UP when [agent_next] is absent."""
    if not isinstance(settings.read_global().get("agent_next"), dict):
        return None, NOT_SET_UP
    try:
        return ctx.ad.agentnext.get_json("/status"), ""
    except agentnext.AgentUnavailable as err:
        return None, str(err)


def check_agentkit_service(ctx):
    """The new agent's service is active and answers /status."""
    status, reason = _agentkit_status(ctx)
    if reason == NOT_SET_UP:
        return _result(True, f"the new agent is {NOT_SET_UP}")
    rc, out, _ = ctx.ad.host.systemctl("is-active", AGENTKIT_UNIT)
    state = out.split()[0] if out.split() else "unknown"
    fix = f"Start it with `systemctl start {AGENTKIT_UNIT}`, then read `journalctl -u {AGENTKIT_UNIT}`."
    if rc != 0 or state != "active":
        return _result(False, f"{AGENTKIT_UNIT} is {state}", fix)
    if status is None:
        return _result(False, f"{AGENTKIT_UNIT} is active but does not answer: {reason}", fix)
    return _result(True, f"{AGENTKIT_UNIT} is active and answering")


def check_agentkit_key(ctx):
    """The new agent has its API key (as it reports itself; the key file is never read here)."""
    status, reason = _agentkit_status(ctx)
    if reason == NOT_SET_UP:
        return _result(True, f"the new agent is {NOT_SET_UP}")
    if status is None:
        return _result(False, f"cannot ask the new agent about its key: {reason}", "Fix the agentkit-service line first.")
    present = status.get("key_present") is True
    return _result(present, "the new agent has its API key" if present else "the new agent has no API key yet",
                   "Put the key in the agent's key file (see deploy/agentkit/README.md).")


def check_agentkit_spend(ctx):
    """How much of this month's allowance the new agent has used, in words only."""
    status, reason = _agentkit_status(ctx)
    if reason == NOT_SET_UP:
        return _result(True, f"the new agent is {NOT_SET_UP}")
    if status is None:
        return _result(False, f"cannot ask the new agent about its allowance: {reason}", "Fix the agentkit-service line first.")
    try:
        state = ctx.ad.agentnext.get_json("/spend").get("state")
    except agentnext.AgentUnavailable as err:
        return _result(False, f"cannot ask the new agent about its allowance: {err}", "Fix the agentkit-service line first.")
    ok, words = SPEND_WORDS.get(state, (False, "unknown"))
    detail = f"the new agent's allowance: {words}"
    if state == "low":
        detail = "Warning: " + detail
    return _result(ok, detail, "Wait for next month, or ask Alex to raise the agent's monthly allowance.")


CHECKS = {"python": check_python, "library": check_library, "services": check_services,
          "service-home": check_service_home, "api": check_api,
          "origins": check_origins, "upstream": check_upstream,
          "home": check_home, "secrets": check_secrets, "images": check_images, "proxy-rule": check_proxy_rule,
          "firewall": check_firewall, "claude": check_claude, "advisor": check_advisor, "disk": check_disk, "updater": check_updater,
          "project-links": check_project_links, "memory-files": check_memory_files, "reference": check_reference,
          "agent-unit": check_agent_unit, "agent-session": check_agent_session, "agent-socket": check_agent_socket,
          "agent-transcript": check_agent_transcript, "agent-folder": check_agent_folder,
          "agent-pack": check_agent_pack, "agent-helpers": check_agent_helpers, "agent-rules": check_agent_rules,
          "project-chats": check_project_chats, "access": check_access,
          "agentkit-service": check_agentkit_service, "agentkit-key": check_agentkit_key, "agentkit-spend": check_agentkit_spend}


def run_checks(adapters, mode: str = "full") -> dict:
    """Run the checks for a mode; returns {ok, checks: [{name, ok, detail, fix}]}."""
    if mode not in MODES:
        raise ValueError(f"unknown doctor mode: {mode}")
    ctx = Context(adapters, mode)
    checks = []
    for name in CHECKS_BY_MODE[mode]:
        try:
            ok, detail, fix = CHECKS[name](ctx)
        except Exception as err:        # one broken check must not stop the others
            ok, detail, fix = False, f"the check itself failed ({type(err).__name__})", "Run it again; if it repeats, read the logs."
        checks.append({"name": name, "ok": bool(ok), "detail": scrub.scrub(detail), "fix": fix})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def render(data: dict) -> str:
    """The plain-words report: one line per check, the fix under a failed one, then a summary."""
    lines = []
    for c in data["checks"]:
        lines.append(f"{'OK     ' if c['ok'] else 'PROBLEM'} {c['name']}: {c['detail']}")
        if not c["ok"] and c["fix"]:
            lines.append(f"        Fix: {c['fix']}")
    bad = sum(not c["ok"] for c in data["checks"])
    lines.append("All good." if not bad else f"{bad} problem{'s' if bad != 1 else ''}.")
    return "\n".join(lines)
