"""Adapters: every outside tool (docker, claude, git, host, http, clock, notify, chat, proxy) behind one object."""
import ipaddress
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phoenix9.docker import DockerRunner

NOTIFY_MAX = 600
TCP_TABLES = ("/proc/net/tcp", "/proc/net/tcp6")


def _proc_addr(text: str):
    """(ip address, port) of one /proc/net/tcp address ('0100007F:1F9F'); IPv4-mapped IPv6 reads as IPv4."""
    hexip, hexport = text.split(":")
    raw = bytes.fromhex(hexip)
    raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))   # each 32-bit word is little-endian
    ip = ipaddress.ip_address(raw)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip, int(hexport, 16)


def _norm(addr):
    """(ip address, port) of a socket address tuple, with IPv4-mapped IPv6 as IPv4."""
    ip = ipaddress.ip_address(addr[0].split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip, int(addr[1])
DEFAULT_NOTIFY_FILE = "/srv/phoenix-inbox/jobs/notify.msg"


class Host:
    """The real host: systemctl, gh, du and plain commands."""

    def run(self, argv: list[str], timeout: float = 60, cwd=None) -> tuple[int, str, str]:
        """Run a command (in cwd if given) and return (exit code, stdout, stderr); 124 on timeout, 127 if not found."""
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               cwd=cwd)
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout}s"
        except FileNotFoundError:
            return 127, "", f"not found: {argv[0]}"
        return p.returncode, p.stdout, p.stderr

    def systemctl(self, *args: str) -> tuple[int, str, str]:
        """Run systemctl with the given arguments."""
        return self.run(["systemctl", *args])

    def gh(self, *args: str) -> tuple[int, str, str]:
        """Run the GitHub command line tool with the given arguments."""
        return self.run(["gh", *args], timeout=120)

    def read_text(self, path) -> str:
        """Read a text file on the host (FileNotFoundError when it is not there)."""
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path, text: str, mode: int = 0o600) -> None:
        """Write a text file on the host in one swap, keeping it owner-only by default."""
        from phoenix9 import atomic
        atomic.write_text(Path(path), text, mode)

    def du_bytes(self, path) -> int:
        """Return the size of a folder in bytes (0 if it cannot be measured)."""
        rc, out, _ = self.run(["du", "-sb", str(path)])
        if rc != 0 or not out.split():
            return 0
        return int(out.split()[0])

    def list_dir(self, path) -> list[str]:
        """List the names in a folder ([] when it is missing or unreadable)."""
        try:
            return os.listdir(path)
        except OSError:
            return []

    def exists(self, path) -> bool:
        """Say whether a path exists."""
        return os.path.exists(path)

    def pid_alive(self, pid) -> bool:
        """Say whether a process with this id is running."""
        try:
            os.kill(int(pid), 0)
        except PermissionError:
            return True      # it is there, just not ours to signal
        except (ProcessLookupError, ValueError, OverflowError, TypeError):
            return False
        return True

    def socket_uid(self, local, remote, tables=TCP_TABLES) -> int | None:
        """The uid owning the TCP socket whose own end is `local` and far end is `remote` (address tuples),
        read from /proc/net/tcp and tcp6; None when there is no such socket or more than one owner."""
        want = (_norm(local), _norm(remote))
        uids = set()
        for table in tables:
            try:
                rows = open(table, encoding="ascii").read().splitlines()[1:]
            except OSError:
                continue
            for row in rows:
                parts = row.split()
                try:
                    if (_proc_addr(parts[1]), _proc_addr(parts[2])) == want:
                        uids.add(int(parts[7]))
                except (IndexError, ValueError):
                    continue
        return uids.pop() if len(uids) == 1 else None

    def realpath(self, path) -> str:
        """The path with every symlink resolved (the path itself when it cannot be resolved)."""
        return os.path.realpath(path)

    def stat(self, path) -> dict | None:
        """Return {mode, uid, mtime} of a path, or None when it is missing."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        return {"mode": st.st_mode & 0o7777, "uid": st.st_uid, "mtime": st.st_mtime}

    def read_lines(self, path) -> list[str]:
        """Read a text file as lines ([] when it is missing)."""
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            return []


class Clock:
    """The real clock."""

    def now(self) -> float:
        """Return the current time in seconds since 1970."""
        return time.time()

    def sleep(self, s: float) -> None:
        """Wait for s seconds."""
        time.sleep(s)


class Notify:
    """Sends a message to Alex by writing the file that phoenix-notify.path picks up."""

    def send(self, text: str) -> None:
        """Write the message (cut to 600 characters) to the notify file."""
        path = Path(os.environ.get("PHOENIX_NOTIFY_FILE") or DEFAULT_NOTIFY_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text[:NOTIFY_MAX])


class Http:
    """Plain web requests with urllib."""

    def request(self, method: str, url: str, headers: dict | None = None, body: bytes | None = None,
                timeout: float = 30) -> tuple[int, dict, bytes]:
        """Send a request and return (status, headers, body); HTTP errors return their status."""
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


class Chat:
    """Delegate mode: hands a failed task to the project's own chat agent (phoenix9/chat.py)."""

    def delegate(self, project: str, project_dir, gate: str, prompt: str, log_path) -> dict:
        """Start the detached project chat session; returns {"started", "handle", "error"}."""
        from phoenix9 import chat
        return chat.delegate(project, project_dir, gate, prompt, log_path)

    def status(self, handle: str) -> str:
        """"running" or "exited"."""
        from phoenix9 import chat
        return chat.status(handle)

    def stop(self, handle):
        """Stop a delegate session that is still running (e.g. Alex answered first)."""
        from phoenix9 import chat
        chat.stop(handle)


class Claude:
    """Real claude adapter; filled in by step 09."""

    def launch(self, docker, *, ai: dict, project: str, run_id: str, task, attempt: int, role: str,
               image: str, workspace, prompt_file, step_dir, project_dir, spec_dir=None,
               domains_file=None, env_files=(), workspace_ro=False, extra_mounts=(), extra_env=None):
        """Run one Claude session in a step container (trying fallback models) and return its Result."""
        from phoenix9 import claude as cl
        from phoenix9 import docker as dk
        mounts = [*cl.session_mounts(ai, step_dir, project_dir), *extra_mounts]
        note = cl.advisor_note(ai)
        if note:
            text = Path(prompt_file).read_text(encoding="utf-8")
            if note not in text:
                Path(prompt_file).write_text(f"{text.rstrip()}\n\n{note}\n", encoding="utf-8")

        def one(model: str):
            cmd = cl.build_command({**ai, "model": model}, dk.PROMPT_MOUNT, "/workspace")
            rc, log = dk.run_claude_container(
                docker, project, run_id, task, attempt, role, image, workspace, prompt_file, cmd,
                float(ai.get("timeout") or 30), env_files=list(env_files), domains_file=domains_file,
                spec_dir=spec_dir, mounts=mounts, workspace_ro=workspace_ro, extra_env=extra_env)
            return cl.parse(log, rc)
        return cl.run_with_fallback(ai, one)

    def __getattr__(self, name: str):
        """Methods not written yet raise NotImplementedError."""
        raise NotImplementedError(f"claude.{name} is not written yet")


class Git:
    """Real git adapter: every public function of phoenix9.git, as a method."""

    def __getattr__(self, name: str):
        """Look the function up in phoenix9.git."""
        from phoenix9 import git as git_module
        if name.startswith("_") or not hasattr(git_module, name):
            raise AttributeError(f"git.{name} does not exist")
        return getattr(git_module, name)


class Proxy:
    """Starts the per-step key proxy (phoenix9/proxy.py) on this host."""

    def start(self, spec, key: str, *, log_path, step: str, bind: str = "127.0.0.1", ports=None):
        """Start a proxy for one service and step on the first free port of the fixed range
        (global.toml `proxy_ports`, default 47100-47199); returns the handle (.url, .token, .port, .stop())."""
        from phoenix9 import proxy, settings
        return proxy.serve(spec, key, log_path=Path(log_path), step=step, bind=bind,
                           ports=tuple(ports) if ports else settings.proxy_ports())


@dataclass
class Adapters:
    """Everything outside Phoenix, in one place; tests swap in fakes."""

    docker: Any
    claude: Any
    git: Any
    host: Any
    http: Any
    clock: Any
    notify: Any
    chat: Any
    proxy: Any = None


def real() -> Adapters:
    """Build the real adapters (nothing touches the system until a method is called)."""
    return Adapters(docker=DockerRunner(), claude=Claude(), git=Git(), host=Host(), http=Http(),
                    clock=Clock(), notify=Notify(), chat=Chat(), proxy=Proxy())
