"""Starting the throwaway Docker containers that each step runs in.

The container is the safety boundary for every Claude session. Each one is
fresh, firewalled (only allowed sites can be reached), has limited memory,
CPU and process count, and is removed when it ends. A container never gets
Docker control, the GitHub token or ~/.ssh (hard rule 2).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from phoenix import claude, config, hostpaths

DOCKER = "docker"
ENTRY = "/opt/hands/entry.sh"                       # baked into the image (image/Dockerfile)
DOMAINS_MOUNT = "/etc/hands/allowed-domains"        # where image/init-firewall.sh reads extra hosts
PROMPT_MOUNT = "/phoenix/prompt.md"
SYSTEM_PROMPT_MOUNT = "/phoenix/system-prompt.md"
HOOKS_MOUNT = "/phoenix-hooks"
SETTINGS_MOUNT = "/home/node/.claude/settings.json"
TRANSCRIPT_MOUNT = "/home/node/.claude/projects"
STORE_MOUNT = "/pnpm-store"
LABEL = "phoenix"
HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
FALLBACK_UID = 1000                                 # entry.sh refuses uid 0; the image's `node` user
TIMEOUT_RC = 124
FORBIDDEN_ENV_FILES = ("github.env",)               # hard rule 2: never inside a step container

# Hosts every project may reach, on top of init-firewall.sh's own two
# (api.anthropic.com, registry.npmjs.org). Kept identical on purpose so the
# domains file is complete on its own.
BUILTIN_DOMAINS = ("api.anthropic.com", "registry.npmjs.org")


# ------------------------------------------------------------- argv building
# Borrowed from Phoenix 0.6.0 hands/docker.py:16-32
@dataclass
class Mount:
    """One thing mounted into a container: a host path (Path) or a named volume (str)."""

    src: Path | str
    dst: str
    ro: bool = True

    def arg(self) -> str:
        """Return the value for `docker run --mount`.

        A bind source is given as its path on the Docker host (see hostpaths:
        when Phoenix runs in its own container the two differ).
        """
        if isinstance(self.src, Path):
            src = self.src.resolve()
            if not src.exists():
                raise FileNotFoundError(f"bind source missing: {src}")
            src = hostpaths.to_host(src)
            spec = f"type=bind,src={src},dst={self.dst}"
        else:
            src = self.src
            spec = f"type=volume,src={self.src},dst={self.dst}"
        if "," in str(src) or "," in self.dst:
            raise ValueError(f"comma in mount path: {spec}")
        return spec + (",readonly" if self.ro else "")


@dataclass
class Run:
    """Everything needed to start one container."""

    run_id: str
    step: int | str
    try_no: int
    role: str
    cmd: list[str]
    mounts: list[Mount] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_files: list[Path] = field(default_factory=list)
    firewall: bool = True               # False = no network at all (--network none), no NET_ADMIN


def container_name(run_id: str, step: int | str, try_no: int, role: str) -> str:
    """Return the container name `phoenix-<run>-<step>-<try>-<role>`."""
    return f"phoenix-{run_id}-{step}-{try_no}-{role}"


def agent_ids() -> tuple[int, int]:
    """Return the uid/gid the session runs as inside the container.

    entry.sh refuses uid 0, so when Phoenix itself runs as root the image's
    `node` user (1000) is used and Phoenix hands it the folders it writes.
    """
    if os.getuid() == 0:
        return FALLBACK_UID, FALLBACK_UID
    return os.getuid(), os.getgid()


# Borrowed from Phoenix 0.6.0 hands/docker.py:61-89 (labels and settings renamed for v8)
def build_argv(r: Run, settings: dict | None = None) -> list[str]:
    """Return the full `docker run ...` command for one container."""
    s = settings or config.load()
    uid, gid = agent_ids()
    memory = str(s["container_memory"])
    argv = [
        DOCKER, "run", "--rm", "-i", "--init",
        "--name", container_name(r.run_id, r.step, r.try_no, r.role),
        "--label", f"{LABEL}=1",
        "--label", f"{LABEL}.run={r.run_id}",
        "--label", f"{LABEL}.role={r.role}",
        "--user", "0:0", "--entrypoint", ENTRY,
        "--shm-size", "1g",
        "-e", "TZ=UTC",
        "--memory", memory, "--memory-swap", memory,
        "--cpus", str(s["container_cpus"]), "--pids-limit", str(s["container_pids"]),
        "--security-opt", "no-new-privileges",
        "-e", f"HOST_UID={uid}", "-e", f"HOST_GID={gid}",
        "-e", f"HANDS_ROLE={r.role}",
        "-w", "/workspace",
    ]
    if r.firewall:
        argv += ["--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "-e", "HANDS_FIREWALL=1"]
    else:
        argv += ["--network", "none", "-e", "HANDS_FIREWALL=0"]
    for k, v in r.env.items():
        argv += ["-e", f"{k}={v}"]
    for f in r.env_files:
        if Path(f).name in FORBIDDEN_ENV_FILES:
            raise ValueError(f"{Path(f).name} must never be passed to a step container")
        argv += ["--env-file", str(f)]
    for m in r.mounts:
        argv += ["--mount", m.arg()]
    argv += [str(s["image"]), *r.cmd]
    return argv


# ------------------------------------------------------------- running and stopping
# Borrowed from Phoenix 0.6.0 hands/docker.py:122-147
def _execute(argv: list[str], name: str, stdout_p: Path | None, stderr_p: Path | None,
             timeout_s: float, append_stdout: bool = False) -> int:
    """Run a container to the end and return its exit code (124 if it ran out of time)."""
    stdout = open(stdout_p, "ab" if append_stdout else "wb") if stdout_p else subprocess.DEVNULL
    if stderr_p and stderr_p == stdout_p:
        stderr = subprocess.STDOUT
    else:
        stderr = open(stderr_p, "ab") if stderr_p else subprocess.DEVNULL
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill(name)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
            return TIMEOUT_RC
        except BaseException:
            kill(name)
            raise
    finally:
        for fh in (stdout, stderr):
            if hasattr(fh, "close"):
                fh.close()


# Borrowed from Phoenix 0.6.0 hands/docker.py:150-151
def kill(name: str) -> None:
    """Force-remove a container by name (no error if it is not there)."""
    subprocess.run([DOCKER, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Borrowed from Phoenix 0.6.0 hands/docker.py:154-161
def cleanup_orphans(run_id: str | None = None) -> int:
    """Remove leftover Phoenix containers (all of them, or one run's). Returns how many."""
    label = f"{LABEL}.run={run_id}" if run_id else f"{LABEL}=1"
    out = subprocess.run([DOCKER, "ps", "-aq", "--filter", f"label={label}"],
                         capture_output=True, text=True).stdout.split()
    for cid in out:
        subprocess.run([DOCKER, "rm", "-f", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return len(out)


def volume_create(name: str, run_id: str) -> str:
    """Create a fresh named Docker volume (labelled with the run) and return its name."""
    subprocess.run([DOCKER, "volume", "create", "--label", f"{LABEL}=1", "--label", f"{LABEL}.run={run_id}",
                    name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return name


def volume_rm(name: str) -> None:
    """Remove a named Docker volume (no error if it is not there)."""
    subprocess.run([DOCKER, "volume", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hand_to_agent(path: Path) -> None:
    """Make a host folder writable by the container's session user.

    Only needed when Phoenix runs as root (the session then runs as uid 1000).
    """
    if os.getuid() != 0:
        return
    uid, gid = agent_ids()
    subprocess.run(["chown", "-R", f"{uid}:{gid}", str(path)], check=True)


# ------------------------------------------------------------- Claude sessions
def claude_env_file() -> Path:
    """Return the path of claude.env (holds CLAUDE_CODE_OAUTH_TOKEN)."""
    return config.paths().config / "claude.env"


def pnpm_store_dir() -> Path:
    """Return the shared pnpm store folder used by builder sessions (created if missing)."""
    d = config.paths().cache / "pnpm-store"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_dir(run_id: str, step: int | str, try_no: int, role: str) -> Path:
    """Return runs/<id>/prompts/<step>-<try>-<role>/, where the session transcript is kept."""
    return config.paths().runs / run_id / "prompts" / f"{step}-{try_no}-{role}"


def session_env(scrub: bool = False) -> dict[str, str]:
    """Environment for a Claude session container (no secrets: those come from env files).

    CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is always set, to 1 or 0 from the
    phoenix.toml setting `subprocess_env_scrub` (default off): with 1, Claude
    Code needs a bubblewrap sandbox, which cannot start inside the hardened
    container, so every Bash command the session runs fails.
    """
    return {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1" if scrub else "0",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "DISABLE_AUTOUPDATER": "1",
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_HOME": "/home/node/.cache/corepack",
        "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "npm_config_store_dir": STORE_MOUNT,
        "CI": "1",
    }


def hook_mounts(hooks_dir: Path = HOOKS_DIR) -> list[Mount]:
    """Read-only mounts for the hooks folder and, if it has one, its settings.json.

    Mounted read-only so the session cannot change its own hook settings.
    """
    if not hooks_dir.is_dir():
        return []
    mounts = [Mount(hooks_dir, HOOKS_MOUNT)]
    if (hooks_dir / "settings.json").is_file():
        mounts.append(Mount(hooks_dir / "settings.json", SETTINGS_MOUNT))
    return mounts


def claude_run(run_id: str, step: int | str, try_no: int, role: str, workspace: Path, prompt_file: Path,
               env_files: list[Path], allowed_domains_file: Path | None, *, max_turns: int = 200,
               allowed_tools: list[str] = (), disallowed_tools: list[str] = (),
               system_prompt_file: Path | None = None, scrub: bool = False, mounts=()) -> Run:
    """Describe the container for one Claude session (only the transcript folder is created).

    `mounts` are extra mounts (the builder gets the test configs and a report folder).
    """
    tdir = transcript_dir(run_id, step, try_no, role)
    tdir.mkdir(parents=True, exist_ok=True)
    all_mounts = [Mount(Path(workspace), "/workspace", ro=False),
                  Mount(Path(prompt_file), PROMPT_MOUNT),
                  *hook_mounts(),
                  Mount(pnpm_store_dir(), STORE_MOUNT, ro=False),
                  Mount(tdir, TRANSCRIPT_MOUNT, ro=False)]
    if allowed_domains_file:
        all_mounts.append(Mount(Path(allowed_domains_file), DOMAINS_MOUNT))
    if system_prompt_file:
        all_mounts.append(Mount(Path(system_prompt_file), SYSTEM_PROMPT_MOUNT))
    all_mounts += list(mounts)
    cmd = claude.build_command(PROMPT_MOUNT, "/workspace", max_turns, list(allowed_tools),
                               list(disallowed_tools), SYSTEM_PROMPT_MOUNT if system_prompt_file else None)
    return Run(run_id, step, try_no, role, cmd, mounts=all_mounts, env=session_env(scrub),
               env_files=[claude_env_file(), *map(Path, env_files)])


def run_claude_container(run_id: str, step: int | str, try_no: int, role: str, workspace: Path,
                         prompt_file: Path, env_files: list[Path], allowed_domains_file: Path | None,
                         timeout_min: float, *, no_output_timeout_min: float | None = None,
                         max_turns: int = 200, allowed_tools: list[str] = (),
                         disallowed_tools: list[str] = (), system_prompt_file: Path | None = None,
                         settings: dict | None = None, mounts=()) -> claude.Result:
    """Run one Claude session in a fresh firewalled container and return its Result.

    `env_files` are the project's test env files; claude.env is added here.
    The session's stream goes to runs/<id>/logs/<step>-<try>-<role>.jsonl
    (secrets redacted) and its transcript to runs/<id>/prompts/<step>-<try>-<role>/.
    """
    s = settings or config.load()
    r = claude_run(run_id, step, try_no, role, workspace, prompt_file, env_files, allowed_domains_file,
                   max_turns=max_turns, allowed_tools=allowed_tools, disallowed_tools=disallowed_tools,
                   system_prompt_file=system_prompt_file, scrub=bool(s["subprocess_env_scrub"]),
                   mounts=mounts)
    argv = build_argv(r, s)
    name = container_name(run_id, step, try_no, role)
    hand_to_agent(Path(workspace))
    hand_to_agent(transcript_dir(run_id, step, try_no, role))
    kill(name)                                   # a leftover with the same name would block the start

    def start(cmd, cwd, files):
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    log_path = config.paths().runs / run_id / "logs" / f"{step}-{try_no}-{role}.jsonl"
    no_output = no_output_timeout_min if no_output_timeout_min is not None else s["no_output_timeout_min"]
    try:
        # the secrets list comes from the project env files plus claude.env (all redacted from the log)
        return claude.run(r.cmd, Path(workspace), r.env_files, log_path, timeout_min, no_output, start=start)
    finally:
        kill(name)


# ------------------------------------------------------------- check containers
def run_check_container(run_id: str, step: int | str, try_no: int, checkout: Path, command: str,
                        env_file: Path | None, allowed_domains_file: Path | None, timeout_min: float,
                        *, stdout_path: Path | None = None, role: str = "check", firewall: bool = True,
                        mounts: list[Mount] = (), settings: dict | None = None) -> tuple[int, Path]:
    """Run one shell command in a throwaway check container. Returns (exit code, output file).

    No Claude token. `/workspace` is the given checkout, the pnpm store is a
    fresh volume that is removed afterwards. The command's stdout and stderr
    go to a host file (default runs/<id>/logs/<step>-<try>-<role>.txt), so
    nothing inside the container can forge it; values from the env file are
    redacted from it afterwards. Exit code 124 means it ran out of time.
    `mounts` are extra mounts (the test configs, the report folder).
    """
    s = settings or config.load()
    out = Path(stdout_path) if stdout_path else config.paths().runs / run_id / "logs" / f"{step}-{try_no}-{role}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    name = container_name(run_id, step, try_no, role)
    store = f"{name}-pnpm"
    r = check_run(run_id, step, try_no, role, Path(checkout), command, env_file, allowed_domains_file,
                  store, firewall, mounts)
    argv = build_argv(r, s)
    hand_to_agent(Path(checkout))
    kill(name)
    volume_rm(store)
    volume_create(store, run_id)
    try:
        # Borrowed from Phoenix 0.6.0 hands/loop.py:815-851 (output capture: the container's
        # stdout and stderr into one host file, then redacted)
        rc = _execute(argv, name, out, out, timeout_min * 60)
    finally:
        kill(name)
        volume_rm(store)
    secrets = claude.secrets_from(r.env_files)
    if secrets:
        out.write_text(claude.redact(out.read_text(errors="replace"), secrets))
    return rc, out


def check_run(run_id: str, step: int | str, try_no: int, role: str, checkout: Path, command: str,
              env_file: Path | None, allowed_domains_file: Path | None, store: str,
              firewall: bool = True, extra_mounts: list[Mount] = ()) -> Run:
    """Describe a check container (nothing is started here). Never gets claude.env."""
    if env_file and Path(env_file).name == "claude.env":
        raise ValueError("a check container never gets the Claude token")
    mounts = [Mount(checkout, "/workspace", ro=False), Mount(store, STORE_MOUNT, ro=False)]
    if allowed_domains_file and firewall:
        mounts.append(Mount(Path(allowed_domains_file), DOMAINS_MOUNT))
    mounts += list(extra_mounts)
    env = {k: v for k, v in session_env().items() if not k.startswith("CLAUDE_")}
    return Run(run_id, step, try_no, role, ["bash", "-c", command], mounts=mounts, env=env,
               env_files=[Path(env_file)] if env_file else [], firewall=firewall)


# ------------------------------------------------------------- firewall probe
# Borrowed from Phoenix 0.6.0 hands/__main__.py:525-549. Runs as the session user inside a
# probe container. Every line is a marker read by firewall_checks; the last line is the uid.
FIREWALL_PROBE = (
    "curl -s --connect-timeout 5 https://example.com >/dev/null && echo LEAK || echo blocked; "
    "curl -s --connect-timeout 5 http://1.1.1.1/ >/dev/null && echo LEAK-IP || echo ip-blocked; "
    "curl -s -o /dev/null -w 'anthropic=%{http_code}\\n' https://api.anthropic.com; "
    "iptables -F 2>/dev/null && echo FLUSHED || echo cannot-flush; "
    "sudo -n true 2>/dev/null && echo SUDO || echo no-sudo; "
    "curl -s -6 --connect-timeout 5 https://example.com >/dev/null && echo LEAK6 || echo v6-blocked; "
    "getent hosts api.anthropic.com >/dev/null && echo dns-allowed-ok || echo DNS-ALLOWED-FAILED; "
    "getent hosts probe-$RANDOM$RANDOM.example.com >/dev/null && echo DNS-RANDOM-RESOLVED || echo dns-random-blocked; "
    "for ns in 1.1.1.1 8.8.8.8; do for t in '' '+tcp'; do "
    "dig $t +short +time=3 +tries=1 @$ns example.com 2>/dev/null | grep -v '^;' | grep -q . "
    "&& echo DNS-OPEN-$ns${t:-+udp} || echo dns-direct-blocked-$ns${t:-+udp}; done; done; "
    "pgrep -x dnsmasq >/dev/null && echo dnsmasq-running || echo DNSMASQ-MISSING; "
    "pkill -x dnsmasq 2>/dev/null; pkill -9 -x dnsmasq 2>/dev/null; sleep 1; "
    "pgrep -x dnsmasq >/dev/null && echo dnsmasq-survived || echo DNSMASQ-KILLED; "
    "touch /run/hands-dns/dnsmasq.conf 2>/dev/null && echo DNSCONF-WRITABLE || echo dnsconf-readonly; "
    "timeout 5 bash -c 'exec 3<>/dev/tcp/140.82.112.3/22' 2>/dev/null && echo LEAK-SSH || echo ssh-blocked; "
    "timeout 5 bash -c 'exec 3<>/dev/tcp/140.82.112.3/443' 2>/dev/null && echo LEAK-GHIP || echo ghip-blocked; "
    "getent hosts api.github.com >/dev/null && echo GH-DNS-RESOLVED || echo gh-dns-blocked; "
    "curl -s -o /dev/null -w 'github=%{http_code}\\n' --connect-timeout 5 https://api.github.com/zen; "
    "GW=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}'); "
    "[ -n \"$GW\" ] && timeout 5 bash -c \"exec 3<>/dev/tcp/$GW/22\" 2>/dev/null && echo LEAK-HOST || echo host-blocked; "
    "id -u"
)


# Borrowed from Phoenix 0.6.0 hands/__main__.py:552-583 (the project allowlist argument dropped:
# the doctor probe always runs with the built-in hosts only)
def firewall_checks(out: str) -> list[tuple[bool, str]]:
    """Turn the probe's output markers into (passed, label) pairs."""
    lines = out.split()
    has = lines.__contains__
    return [
        (has("blocked") and not has("LEAK"), "egress blocked for non-allowlisted sites (example.com)"),
        (has("ip-blocked") and not has("LEAK-IP"), "egress blocked to a raw outside IP (1.1.1.1:80)"),
        (any(l.startswith("anthropic=") and l != "anthropic=000" for l in lines), "api.anthropic.com reachable"),
        (has("cannot-flush") and has("no-sudo"), "session cannot change the firewall or use sudo"),
        (has("v6-blocked") and not has("LEAK6"), "no IPv6 egress"),
        (has("dns-allowed-ok"), "DNS: allowlisted name resolves"),
        (has("dns-random-blocked"), "DNS: non-allowlisted name does not resolve"),
        (not any(l.startswith("DNS-OPEN-") for l in lines)
         and sum(l.startswith("dns-direct-blocked-") for l in lines) == 4,
         "DNS: direct queries to 1.1.1.1/8.8.8.8 (udp+tcp) blocked"),
        (has("dnsmasq-running") and has("dnsmasq-survived") and has("dnsconf-readonly"),
         "DNS: session cannot kill or reconfigure dnsmasq"),
        (has("ssh-blocked") and not has("LEAK-SSH"), "egress blocked on tcp/22 to an outside IP"),
        (has("host-blocked") and not has("LEAK-HOST"), "egress blocked to the host (default gateway)"),
        (has("ghip-blocked") and not has("LEAK-GHIP"), "egress blocked to a GitHub IP"),
        (has("gh-dns-blocked") and has("github=000"), "api.github.com unreachable"),
    ]


def probe_firewall(settings: dict | None = None, timeout_min: float = 3) -> list[str]:
    """Start a firewalled container and test it. Returns the failures ([] means all good).

    Confirms (among other things) that example.com is blocked and
    api.anthropic.com answers.
    """
    s = settings or config.load()
    out = config.paths().cache / "doctor" / "firewall-probe.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = Run("doctor", 0, 0, "probe", ["bash", "-c", FIREWALL_PROBE])
    rc = _execute(build_argv(r, s), container_name("doctor", 0, 0, "probe"), out, out, timeout_min * 60)
    text = out.read_text(errors="replace")
    failures = [label for ok, label in firewall_checks(text) if not ok]
    if rc != 0 and not failures:
        failures.append(f"probe container exited with {rc}")
    if failures and rc != 0:
        failures.append(f"container output (exit {rc}):\n{text[-2000:]}")
    return failures


# ------------------------------------------------------------- allowed domains
def domains_file_path(repo: str) -> Path:
    """Return config/projects/<repo-name>.domains for a repo written `owner/name`."""
    return config.paths().config / "projects" / f"{repo.split('/')[-1]}.domains"


def write_domains_file(plan) -> Path:
    """Write the project's allowed-hosts file from the plan and return its path.

    One host per line: the built-in hosts first, then the plan's `Sites the
    app may contact` (already checked by plan.check), without duplicates.
    """
    hosts: list[str] = []
    for host in [*BUILTIN_DOMAINS, *plan.sites]:
        host = host.strip()
        if host and host not in hosts:
            hosts.append(host)
    path = domains_file_path(plan.repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(f"{h}\n" for h in hosts))
    os.replace(tmp, path)
    return path
