"""Adapters: every outside tool (docker, claude, git, host, http, clock, notify, chat) behind one object."""
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
DEFAULT_NOTIFY_FILE = "/srv/phoenix-inbox/jobs/notify.msg"


class Host:
    """The real host: systemctl, journalctl, gh, du and plain commands."""

    def run(self, argv: list[str], timeout: float = 60) -> tuple[int, str, str]:
        """Run a command and return (exit code, stdout, stderr); 124 on timeout, 127 if not found."""
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout}s"
        except FileNotFoundError:
            return 127, "", f"not found: {argv[0]}"
        return p.returncode, p.stdout, p.stderr

    def systemctl(self, *args: str) -> tuple[int, str, str]:
        """Run systemctl with the given arguments."""
        return self.run(["systemctl", *args])

    def journal(self, unit: str, lines: int = 50) -> str:
        """Return the last lines of a service's journal."""
        _, out, _ = self.run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager"])
        return out

    def gh(self, *args: str) -> tuple[int, str, str]:
        """Run the GitHub command line tool with the given arguments."""
        return self.run(["gh", *args], timeout=120)

    def du_bytes(self, path) -> int:
        """Return the size of a folder in bytes (0 if it cannot be measured)."""
        rc, out, _ = self.run(["du", "-sb", str(path)])
        if rc != 0 or not out.split():
            return 0
        return int(out.split()[0])


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
    """Delegate mode placeholder (phase 2)."""

    def delegate(self, *args, **kwargs) -> Any:
        """Hand a failure to the project chat agent (not built yet)."""
        raise NotImplementedError("chat delegate is built in phase 2")


class Claude:
    """Real claude adapter; filled in by step 09."""

    def launch(self, docker, *, ai: dict, project: str, run_id: str, task, attempt: int, role: str,
               image: str, workspace, prompt_file, step_dir, project_dir, spec_dir=None,
               domains_file=None, env_files=()):
        """Run one Claude session in a step container (trying fallback models) and return its Result."""
        from phoenix9 import claude as cl
        from phoenix9 import docker as dk
        mounts = cl.session_mounts(ai, step_dir, project_dir)

        def one(model: str):
            cmd = cl.build_command({**ai, "model": model}, dk.PROMPT_MOUNT, "/workspace")
            rc, log = dk.run_claude_container(
                docker, project, run_id, task, attempt, role, image, workspace, prompt_file, cmd,
                float(ai.get("timeout") or 30), env_files=list(env_files), domains_file=domains_file,
                spec_dir=spec_dir, mounts=mounts)
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


def real() -> Adapters:
    """Build the real adapters (nothing touches the system until a method is called)."""
    return Adapters(docker=DockerRunner(), claude=Claude(), git=Git(), host=Host(), http=Http(),
                    clock=Clock(), notify=Notify(), chat=Chat())
