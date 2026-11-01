"""The health checks behind `phoenix doctor`: each check is a small function and one failing check never stops the others."""
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, claude, docker, hold, paths, project, proxy, scrub
from phoenix9.library import read_toml

MODES = ("full", "for-update", "quick")
GB = 1024 ** 3
DISK_FAIL_GB, DISK_WARN_GB = 5, 15
STALE_HOLD_S = 3 * 3600
DEFAULT_API_PORT = 8095
SERVICES = ("phoenix-api", "phoenix-runner")
HOME_FOLDERS = ("config", "secrets", "keys", "runs", "logs")
PROBE_PROFILE = "python-script"
CLAUDE_MODEL = "haiku"
CLAUDE_MINUTES = 5
CHECKS_BY_MODE = {
    "quick": ("services", "api", "home", "secrets", "disk"),
    "for-update": ("services", "api", "home", "images", "firewall"),
    "full": ("python", "library", "services", "api", "home", "secrets", "images", "firewall", "claude",
             "advisor", "disk", "updater"),
}


class Context:
    """What the checks share: the adapters, the mode and what the Claude session found."""

    def __init__(self, adapters, mode: str):
        """Remember the adapters and mode; the Claude check fills in `claude_info`."""
        self.ad = adapters
        self.mode = mode
        self.claude_info: dict | None = None


def _result(ok: bool, detail: str, fix: str = "") -> tuple[bool, str, str]:
    return ok, detail, "" if ok else fix


def _profile_image(name: str) -> str:
    data, _ = read_toml(paths.library() / "profiles" / name / "profile.toml", name)
    return str((data or {}).get("image") or "")


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


def api_port() -> int:
    """The API port from HOME/config/api.env (default 8095)."""
    try:
        text = (paths.config() / "api.env").read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_API_PORT
    m = re.search(r"^\s*PHOENIX_API_PORT\s*=\s*['\"]?(\d+)", text, re.M)
    return int(m.group(1)) if m else DEFAULT_API_PORT


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
    fix = "Restart the API with `systemctl restart phoenix-api` and read `journalctl -u phoenix-api`."
    try:
        status, _, body = ctx.ad.http.request("GET", url, timeout=10)
    except Exception as err:
        return _result(False, f"{url} did not answer ({type(err).__name__})", fix)
    if status != 200:
        return _result(False, f"{url} answered {status}", fix)
    if ctx.mode != "for-update":
        return _result(True, f"{url} answered 200")
    try:
        running = str(json.loads(body.decode("utf-8")).get("tag") or "")
    except ValueError:
        running = ""
    tags = installed_tags(ctx)
    if not tags:
        return _result(False, "the installed copy is not at a release tag", "Check the install folder with `git tag --points-at HEAD`.")
    ok = running in tags
    return _result(ok, f"API runs {running or 'no release'}; installed is {', '.join(tags)}",
                   "The API is still running old code; restart it with `systemctl restart phoenix-api`.")


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


def check_images(ctx):
    """Every profile image a project uses has been built."""
    used = projects_profiles()
    if not used:
        return _result(True, "no projects yet, nothing to check")
    missing = []
    for name in used:
        tag = _profile_image(name)
        if not tag or not ctx.ad.docker.image_exists(tag):
            missing.append(tag or f"profile {name} has no image")
    return _result(not missing, f"{len(used)} profile images present" if not missing
                   else "image missing: " + ", ".join(missing), "Build them with `phoenix images build`.")


def _probe_image(ctx) -> str:
    """The python-script profile's image tag if it exists, else ''."""
    tag = _profile_image(PROBE_PROFILE)
    return tag if tag and ctx.ad.docker.image_exists(tag) else ""


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
    return _result(not failures, "firewall probe passed" if not failures else "; ".join(failures)[:600],
                   "Rebuild the images with `phoenix images build --all` and check Docker's network rules.")


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


CHECKS = {"python": check_python, "library": check_library, "services": check_services, "api": check_api,
          "home": check_home, "secrets": check_secrets, "images": check_images, "firewall": check_firewall,
          "claude": check_claude, "advisor": check_advisor, "disk": check_disk, "updater": check_updater}


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
