"""Starting the throwaway Docker containers that each step runs in.

The container is the safety boundary for every Claude session. Each one is fresh, firewalled (only
allowed sites can be reached), has limited memory, CPU and process count, and is removed when it ends.
A container never gets Docker control, the GitHub token, SSH keys or account service keys (hard rule 2).
Every call to the docker program goes through DockerRunner, so tests can swap in a fake.
"""
from __future__ import annotations

import ipaddress
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from phoenix9 import paths, scrub

DOCKER = "docker"
ENTRY = "/opt/hands/entry.sh"                       # baked into the image (image/Dockerfile)
DOMAINS_MOUNT = "/etc/hands/allowed-domains"        # where image/init-firewall.sh reads extra hosts
ALLOWED_PROXY_MOUNT = "/etc/hands/allowed-proxy"    # `IP PORT` lines: the only host ports init-firewall.sh opens
PROMPT_MOUNT = "/phoenix/prompt.md"
SPEC_MOUNT = "/phoenix/spec"
STORE_MOUNT = "/pnpm-store"
LABEL = "phoenix9"
FALLBACK_UID = 1000                                 # entry.sh refuses uid 0; the image's `node` user
TIMEOUT_RC = 124
FORBIDDEN_ENV_FILES = ("github.env", "telegram.env")              # hard rule 2: never inside a step container
FORBIDDEN_ENV_PATTERNS = ("service-*.env",)         # hard rule 2: account service keys
BUILTIN_DOMAINS = ("api.anthropic.com",)            # init-firewall.sh also allows registry.npmjs.org itself
DEFAULT_LIMITS = {"memory": "4g", "cpus": "1.5", "pids": "512"}


# ------------------------------------------------------------- the one place that runs docker
class DockerRunner:
    """The real docker program: every subprocess call in this module lives here."""

    def bridge_gateway(self) -> str:
        """The default bridge network's gateway address, e.g. 172.17.0.1."""
        out = subprocess.run([DOCKER, "network", "inspect", "bridge", "--format",
                              "{{(index .IPAM.Config 0).Gateway}}"],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        ipaddress.IPv4Address(out)          # refuse anything that is not a plain IPv4 address
        return out

    def run(self, argv: list[str], stdout_path: Path | None, stderr_path: Path | None,
            timeout_s: float, name: str, append_stdout: bool = False) -> int:
        """Run a container to the end and return its exit code (124 if it ran out of time)."""
        # ported from reference/v8/phoenix/docker.py:139
        stdout = open(stdout_path, "ab" if append_stdout else "wb") if stdout_path else subprocess.DEVNULL
        if stderr_path and stderr_path == stdout_path:
            stderr = subprocess.STDOUT
        else:
            stderr = open(stderr_path, "ab") if stderr_path else subprocess.DEVNULL
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            try:
                return p.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self.rm(name)
                try:
                    p.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    p.kill()
                return TIMEOUT_RC
            except BaseException:
                self.rm(name)
                raise
        finally:
            for fh in (stdout, stderr):
                if hasattr(fh, "close"):
                    fh.close()

    def rm(self, name: str) -> None:
        """Force-remove a container by name or id (no error if it is not there)."""
        subprocess.run([DOCKER, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def ps_ids(self, label: str) -> list[str]:
        """Return the ids of all containers (running or not) carrying a label."""
        p = subprocess.run([DOCKER, "ps", "-aq", "--filter", f"label={label}"], capture_output=True, text=True)
        return p.stdout.split()

    def volume_create(self, name: str, labels: list[str]) -> None:
        """Create a named volume with the given labels."""
        argv = [DOCKER, "volume", "create"]
        for label in labels:
            argv += ["--label", label]
        subprocess.run(argv + [name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    def volume_rm(self, name: str) -> None:
        """Remove a named volume (no error if it is not there)."""
        subprocess.run([DOCKER, "volume", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def chown(self, path: Path, uid: int, gid: int) -> None:
        """Hand a host folder to a uid/gid (only used when Phoenix runs as root)."""
        subprocess.run(["chown", "-R", f"{uid}:{gid}", str(path)], check=True)


# ------------------------------------------------------------- argv building
# ported from reference/v8/phoenix/docker.py:40
@dataclass
class Mount:
    """One thing mounted into a container: a host path (Path) or a named volume (str)."""

    src: Path | str
    dst: str
    ro: bool = True

    def arg(self) -> str:
        """Return the value for `docker run --mount`."""
        if isinstance(self.src, Path):
            src = self.src.resolve()
            if not src.exists():
                raise FileNotFoundError(f"bind source missing: {src}")
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

    project: str
    run_id: str
    task: int | str
    attempt: int
    role: str
    image: str
    cmd: list[str]
    mounts: list[Mount] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_files: list[Path] = field(default_factory=list)
    firewall: bool = True               # False = no network at all (--network none), no NET_ADMIN

    @property
    def name(self) -> str:
        """The container's name."""
        return container_name(self.project, self.run_id, self.task, self.attempt, self.role)


def container_name(project: str, run_id: str, task: int | str, attempt: int, role: str) -> str:
    """Return the container name `phoenix9-<project>-<run-id>-<task>-<attempt>-<role>`."""
    return f"phoenix9-{project}-{run_id}-{task}-{attempt}-{role}"


def agent_ids() -> tuple[int, int]:
    """Return the uid/gid the session runs as inside the container (never 0)."""
    # ported from reference/v8/phoenix/docker.py:88
    if os.getuid() == 0:
        return FALLBACK_UID, FALLBACK_UID
    return os.getuid(), os.getgid()


def check_env_file(path: Path | str) -> None:
    """Refuse env files that must never enter a step container (GitHub token, service keys)."""
    import fnmatch
    name = Path(path).name
    if name in FORBIDDEN_ENV_FILES or any(fnmatch.fnmatch(name, p) for p in FORBIDDEN_ENV_PATTERNS):
        raise ValueError(f"{name} must never be passed to a step container")


def check_extra_env(extra_env: dict | None) -> dict:
    """Only proxy address and token variables may be added to a container's env (never an account key)."""
    env = dict(extra_env or {})
    for name in env:
        if not name.startswith("PHOENIX_PROXY_"):
            raise ValueError(f"{name} must not be added to a step container (only PHOENIX_PROXY_* is allowed)")
    return env


def check_mount_source(m: "Mount") -> None:
    """Refuse mounts of the secrets store or of files that hold account keys."""
    if isinstance(m.src, Path):
        check_env_file(m.src)
        if paths.secrets().resolve() in (m.src.resolve(), *m.src.resolve().parents):
            raise ValueError("the secrets folder must never be mounted into a step container")


def build_argv(r: Run, limits: dict | None = None) -> list[str]:
    """Return the full `docker run ...` command for one container."""
    # ported from reference/v8/phoenix/docker.py:100
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    uid, gid = agent_ids()
    memory = str(lim["memory"])
    argv = [
        DOCKER, "run", "--rm", "-i", "--init",
        "--name", r.name,
        "--label", f"{LABEL}=1",
        "--label", f"{LABEL}.project={r.project}",
        "--label", f"{LABEL}.run={r.run_id}",
        "--label", f"{LABEL}.role={r.role}",
        "--user", "0:0", "--entrypoint", ENTRY,
        "--shm-size", "1g",
        "-e", "TZ=UTC", "-e", "PYTHONDONTWRITEBYTECODE=1",   # no .pyc files in the locked checks folder
        "--memory", memory, "--memory-swap", memory,
        "--cpus", str(lim["cpus"]), "--pids-limit", str(lim["pids"]),
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
        check_env_file(f)
        argv += ["--env-file", str(f)]
    for m in r.mounts:
        if "docker.sock" in str(m.src) or "docker.sock" in m.dst:
            raise ValueError("the Docker socket must never be mounted into a step container")
        check_mount_source(m)
        argv += ["--mount", m.arg()]
    argv += [r.image, *r.cmd]
    return argv


# ------------------------------------------------------------- running and stopping
def kill(runner, name: str) -> None:
    """Force-remove a container by name (no error if it is not there)."""
    runner.rm(name)


def cleanup_orphans(runner, run_id: str | None = None) -> int:
    """Remove leftover Phoenix containers (all of them, or one run's). Returns how many."""
    # ported from reference/v8/phoenix/docker.py:174
    label = f"{LABEL}.run={run_id}" if run_id else f"{LABEL}=1"
    ids = runner.ps_ids(label)
    for cid in ids:
        runner.rm(cid)
    return len(ids)


def hand_to_agent(runner, path: Path) -> None:
    """Make a host folder writable by the session user (only needed when Phoenix runs as root)."""
    if os.getuid() != 0:
        return
    uid, gid = agent_ids()
    runner.chown(path, uid, gid)


def session_env(scrub_env: bool = False) -> dict[str, str]:
    """Environment for a Claude session container (no secrets: those come from env files)."""
    # ported from reference/v8/phoenix/docker.py:225
    return {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1" if scrub_env else "0",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "DISABLE_AUTOUPDATER": "1",
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_HOME": "/home/node/.cache/corepack",
        "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "npm_config_store_dir": STORE_MOUNT,
        "CI": "1",
    }


def claude_env_file() -> Path:
    """Return the path of claude.env (holds CLAUDE_CODE_OAUTH_TOKEN)."""
    return paths.secrets() / "claude.env"


def transcript_dir(project: str, run_id: str, task: int | str, attempt: int, role: str) -> Path:
    """Return runs/<project>/<run>/prompts/<task>-<attempt>-<role>/, where the transcript is kept."""
    return paths.runs(project) / run_id / "prompts" / f"{task}-{attempt}-{role}"


def log_path(project: str, run_id: str, task: int | str, attempt: int, role: str, ext: str) -> Path:
    """Return runs/<project>/<run>/logs/<task>-<attempt>-<role>.<ext>."""
    return paths.runs(project) / run_id / "logs" / f"{task}-{attempt}-{role}.{ext}"


# ------------------------------------------------------------- Claude sessions
def claude_run(project: str, run_id: str, task: int | str, attempt: int, role: str, image: str,
               workspace: Path, prompt_file: Path, cmd: list[str], env_files: list[Path] = (),
               domains_file: Path | None = None, spec_dir: Path | None = None, scrub_env: bool = False,
               pnpm_store: Path | None = None, mounts=(), workspace_ro: bool = False,
               extra_env: dict | None = None) -> Run:
    """Describe the container for one Claude session (only the transcript folder is created).

    The spec folder, when given, is mounted read-only (hard rule 4); so is the workspace when `workspace_ro`.
    `cmd` is the claude command line.
    """
    tdir = transcript_dir(project, run_id, task, attempt, role)
    tdir.mkdir(parents=True, exist_ok=True)
    all_mounts = [Mount(Path(workspace), "/workspace", ro=workspace_ro), Mount(Path(prompt_file), PROMPT_MOUNT),
                  Mount(tdir, "/home/node/.claude/projects", ro=False)]
    if spec_dir:
        all_mounts.append(Mount(Path(spec_dir), SPEC_MOUNT, ro=True))
    if pnpm_store:
        all_mounts.append(Mount(Path(pnpm_store), STORE_MOUNT, ro=False))
    if domains_file:
        all_mounts.append(Mount(Path(domains_file), DOMAINS_MOUNT))
    all_mounts += list(mounts)
    return Run(project, run_id, task, attempt, role, image, list(cmd), mounts=all_mounts,
               env={**session_env(scrub_env), **check_extra_env(extra_env)},
               env_files=[claude_env_file(), *map(Path, env_files)])


def run_claude_container(runner, project: str, run_id: str, task: int | str, attempt: int, role: str,
                         image: str, workspace: Path, prompt_file: Path, cmd: list[str],
                         timeout_min: float, *, env_files: list[Path] = (), domains_file: Path | None = None,
                         spec_dir: Path | None = None, scrub_env: bool = False, limits: dict | None = None,
                         pnpm_store: Path | None = None, mounts=(),
                         workspace_ro: bool = False, extra_env: dict | None = None) -> tuple[int, Path]:
    """Run one Claude session in a fresh firewalled container. Returns (exit code, log file).

    The stream goes to runs/<project>/<run>/logs/<task>-<attempt>-<role>.jsonl with secret values
    scrubbed out afterwards. The claude port (step 9) builds `cmd` and reads the log.
    """
    r = claude_run(project, run_id, task, attempt, role, image, workspace, prompt_file, cmd, env_files,
                   domains_file, spec_dir, scrub_env, pnpm_store, mounts, workspace_ro, extra_env)
    argv = build_argv(r, limits)
    out = log_path(project, run_id, task, attempt, role, "jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    hand_to_agent(runner, Path(workspace))
    hand_to_agent(runner, transcript_dir(project, run_id, task, attempt, role))
    runner.rm(r.name)                                  # a leftover with the same name would block the start
    try:
        rc = runner.run(argv, out, None, timeout_min * 60, r.name)
    finally:
        runner.rm(r.name)
    _scrub_file(out, r.env_files)
    return rc, out


def _scrub_file(path: Path, env_files: list[Path]) -> None:
    """Rewrite a log file with the env files' secret values removed."""
    secrets = scrub.secrets_from(env_files)
    if secrets and path.exists():
        path.write_text(scrub.Scrubber(secrets).text(path.read_text(errors="replace")))


# ------------------------------------------------------------- check containers
def check_run(project: str, run_id: str, task: int | str, attempt: int, role: str, image: str,
              checkout: Path, command: str, env_file: Path | None, domains_file: Path | None, store: str,
              firewall: bool = True, extra_mounts: list[Mount] = (), extra_env: dict | None = None) -> Run:
    """Describe a check container (nothing is started here). Never gets claude.env."""
    # ported from reference/v8/phoenix/docker.py:359
    if env_file and Path(env_file).name == "claude.env":
        raise ValueError("a check container never gets the Claude token")
    mounts = [Mount(checkout, "/workspace", ro=False), Mount(store, STORE_MOUNT, ro=False)]
    if domains_file and firewall:
        mounts.append(Mount(Path(domains_file), DOMAINS_MOUNT))
    mounts += list(extra_mounts)
    env = {k: v for k, v in session_env().items() if not k.startswith("CLAUDE_")}
    env.update(check_extra_env(extra_env))
    return Run(project, run_id, task, attempt, role, image, ["bash", "-c", command], mounts=mounts, env=env,
               env_files=[Path(env_file)] if env_file else [], firewall=firewall)


def run_check_container(runner, project: str, run_id: str, task: int | str, attempt: int, image: str,
                        checkout: Path, command: str, env_file: Path | None, domains_file: Path | None,
                        timeout_min: float, *, stdout_path: Path | None = None, role: str = "check",
                        firewall: bool = True, mounts: list[Mount] = (),
                        limits: dict | None = None, extra_env: dict | None = None) -> tuple[int, Path]:
    """Run one shell command in a throwaway check container. Returns (exit code, output file).

    No Claude token. The command's stdout and stderr go to a host file, so nothing inside the container
    can forge it; values from the env file are scrubbed from it. Exit code 124 means it ran out of time.
    """
    # ported from reference/v8/phoenix/docker.py:321
    out = Path(stdout_path) if stdout_path else log_path(project, run_id, task, attempt, role, "txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    name = container_name(project, run_id, task, attempt, role)
    store = f"{name}-pnpm"
    r = check_run(project, run_id, task, attempt, role, image, Path(checkout), command, env_file,
                  domains_file, store, firewall, mounts, extra_env)
    argv = build_argv(r, limits)
    hand_to_agent(runner, Path(checkout))
    runner.rm(name)
    runner.volume_rm(store)
    runner.volume_create(store, [f"{LABEL}=1", f"{LABEL}.run={run_id}"])
    try:
        rc = runner.run(argv, out, out, timeout_min * 60, name)
    finally:
        runner.rm(name)
        runner.volume_rm(store)
    _scrub_file(out, r.env_files)
    return rc, out


# ------------------------------------------------------------- firewall probe
# ported from reference/v8/phoenix/docker.py:377. Runs as the session user inside a probe container.
# Every line is a marker read by firewall_checks; the last line is the uid.
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


def proxy_probe(ip: str, port: int) -> str:
    """Extra probe commands: the allowed proxy address answers (any HTTP code) and its port 22 does not."""
    ipaddress.IPv4Address(ip)
    port = int(port)
    return (f"[ \"$(curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout 5 http://{ip}:{port}/)\" != 000 ] "
            f"&& echo proxy-reachable || echo PROXY-UNREACHABLE; ")


def firewall_checks(out: str, proxy: tuple | None = None) -> list[tuple[bool, str]]:
    """Turn the probe's output markers into (passed, label) pairs; proxy markers only when a proxy was given."""
    # ported from reference/v8/phoenix/docker.py:405
    lines = out.split()
    has = lines.__contains__
    extra = [(has("proxy-reachable") and not has("PROXY-UNREACHABLE"),
              "the allowed key proxy address is reachable")] if proxy else []
    return extra + [
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


def probe_firewall(runner, image: str, limits: dict | None = None, timeout_min: float = 3,
                   proxy: tuple[str, int] | None = None) -> list[str]:
    """Start a firewalled container and test it. Returns the failures ([] means all good).

    With `proxy` = (ip, port) the probe also opens that one address (like a step with a key proxy) and
    checks it answers while the host's other ports stay blocked."""
    # ported from reference/v8/phoenix/docker.py:429
    out = paths.home() / "cache" / "doctor" / "firewall-probe.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    script, mounts = FIREWALL_PROBE, []
    if proxy:
        allow = out.parent / "firewall-probe-proxy.txt"
        allow.write_text(f"{proxy[0]} {int(proxy[1])}\n", encoding="utf-8")
        script = proxy_probe(*proxy) + FIREWALL_PROBE
        mounts = [Mount(allow, ALLOWED_PROXY_MOUNT)]
    r = Run("doctor", "doctor", 0, 0, "probe", image, ["bash", "-c", script], mounts=mounts)
    rc = runner.run(build_argv(r, limits), out, out, timeout_min * 60, r.name)
    text = out.read_text(errors="replace") if out.exists() else ""
    failures = [label for ok, label in firewall_checks(text, proxy) if not ok]
    if rc != 0 and not failures:
        failures.append(f"probe container exited with {rc}")
    if failures and rc != 0:
        failures.append(f"container output (exit {rc}):\n{text[-2000:]}")
    return failures


# ------------------------------------------------------------- allowed domains
def merge_domains(profile_domains=(), project_domains=()) -> list[str]:
    """Return the built-in hosts, then the profile's, then the project's, without duplicates."""
    hosts: list[str] = []
    for host in [*BUILTIN_DOMAINS, *profile_domains, *project_domains]:
        host = host.strip().lower()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def domains_file_path(project: str) -> Path:
    """Return HOME/cache/domains/<project>.domains."""
    return paths.home() / "cache" / "domains" / f"{project}.domains"


def write_domains_file(project: str, profile_domains=(), project_domains=()) -> Path:
    """Write the project's allowed-hosts file (one host per line) and return its path."""
    # ported from reference/v8/phoenix/docker.py:455
    path = domains_file_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(f"{h}\n" for h in merge_domains(profile_domains, project_domains)))
    os.replace(tmp, path)
    return path
