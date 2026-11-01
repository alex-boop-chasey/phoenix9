"""Fake adapters for tests: nothing here touches the real server."""
from pathlib import Path

from phoenix9.adapters import Adapters, Git


class FakeHost:
    """Scripted host: responses chosen by argv prefix; every call is recorded."""

    def __init__(self):
        """Start with no scripted responses."""
        self.calls: list[list[str]] = []
        self.responses: list[tuple[list[str], tuple[int, str, str]]] = []
        self.sizes: dict[str, int] = {}
        self.files: dict[str, str] = {}      # host files (read_text / write_text), by path
        self.cwds: list = []                 # the cwd of each run() call, in step with .calls

    def script(self, prefix: list[str], rc: int = 0, out: str = "", err: str = "") -> None:
        """Answer any command starting with prefix (later scripts win)."""
        self.responses.append((list(prefix), (rc, out, err)))

    def run(self, argv, timeout=60, cwd=None):
        """Record the call and return the scripted answer (default: success, no output)."""
        argv = list(argv)
        self.calls.append(argv)
        self.cwds.append(str(cwd) if cwd else None)
        for prefix, answer in reversed(self.responses):
            if argv[:len(prefix)] == prefix:
                return answer
        return 0, "", ""

    def systemctl(self, *args):
        """Same as run(['systemctl', ...])."""
        return self.run(["systemctl", *args])

    def journal(self, unit, lines=50):
        """Return scripted journal text for the unit."""
        return self.run(["journalctl", "-u", unit, "-n", str(lines)])[1]

    def gh(self, *args):
        """Same as run(['gh', ...])."""
        return self.run(["gh", *args])

    def read_text(self, path):
        """Return a text file set in .files (FileNotFoundError when absent)."""
        if str(path) not in self.files:
            raise FileNotFoundError(str(path))
        return self.files[str(path)]

    def write_text(self, path, text, mode=0o600):
        """Keep the text in .files."""
        self.files[str(path)] = text

    def du_bytes(self, path):
        """Return the size set in .sizes (default 0)."""
        self.calls.append(["du_bytes", str(path)])
        self.cwds.append(None)
        return self.sizes.get(str(path), 0)


class FakeClock:
    """Manual clock: sleep moves time forward instead of waiting."""

    def __init__(self, start: float = 1000.0):
        """Start at the given time."""
        self.t = start
        self.sleeps: list[float] = []

    def now(self):
        """Return the fake time."""
        return self.t

    def sleep(self, s):
        """Advance the fake time by s seconds."""
        self.sleeps.append(s)
        self.t += s


class FakeNotify:
    """Collects messages in a list."""

    def __init__(self):
        """Start empty."""
        self.messages: list[str] = []

    def send(self, text):
        """Remember the message."""
        self.messages.append(text)


class FakeHttp:
    """Canned responses per (method, url); calls are recorded."""

    def __init__(self):
        """Start with no responses."""
        self.responses: dict[tuple[str, str], tuple[int, dict, bytes]] = {}
        self.calls: list[dict] = []

    def script(self, method, url, status=200, headers=None, body=b""):
        """Set the answer for one (method, url)."""
        self.responses[(method.upper(), url)] = (status, headers or {}, body)

    def request(self, method, url, headers=None, body=None, timeout=30):
        """Record the call and return the canned answer (404 if none)."""
        self.calls.append({"method": method.upper(), "url": url, "headers": headers, "body": body})
        return self.responses.get((method.upper(), url), (404, {}, b""))


class FakeChat:
    """Records delegate requests; `mode` scripts what the pretend project chat does.

    answer: it fixes things and answers the gate `acknowledged` as chat:delegate, then exits.
    exit:   it starts, gives up without answering, and exits.
    run:    it starts and keeps running (never answers).
    fail:   it cannot be started.
    `fix` (optional) is called with the gate id before answering (e.g. to write a fix into the worktree).
    `log` lines are written into the log file it is given.
    """

    def __init__(self):
        """Start empty, in answer mode."""
        self.calls: list[tuple] = []
        self.result = None
        self.mode = "answer"
        self.note = "fixed it"
        self.fix = None
        self.log: list[str] = []
        self.running: dict[str, bool] = {}
        self.stopped: list[str] = []

    def delegate(self, *args, **kwargs):
        """Record the request and act out the scripted mode."""
        self.calls.append((args, kwargs))
        if self.result is not None:
            return self.result
        project, project_dir, gate, prompt, log_path = (list(args) + [None] * 5)[:5]
        gate = kwargs.get("gate", gate)
        log_path = kwargs.get("log_path", log_path)
        if self.mode == "fail":
            return {"started": False, "handle": "", "error": "claude: command not found"}
        if log_path and self.log:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text("\n".join(self.log) + "\n")
        handle = f"fake-{len(self.calls)}"
        self.running[handle] = self.mode == "run"
        if self.mode == "answer":
            from phoenix9 import gates
            if self.fix:
                self.fix(gate)
            gates.answer(gate, "acknowledged", note=self.note, who="chat:delegate")
        return {"started": True, "handle": handle, "error": ""}

    def status(self, handle):
        """running while scripted to run; unknown handles (lost in a restart) count as exited."""
        return "running" if self.running.get(handle) else "exited"

    def stop(self, handle):
        """Record the stop and mark the pretend session as ended."""
        self.stopped.append(handle)
        self.running[handle] = False


class FakeDocker:
    """Fake docker runner: records argv, returns scripted exit codes, writes scripted output files."""

    def __init__(self):
        """Start with no calls, a default exit code of 0 and nothing running."""
        self.calls: list[tuple[str, tuple, dict]] = []
        self.argvs: list[list[str]] = []
        self.exit_codes: list[int] = []
        self.outputs: list[str] = []
        self.orphans: list[str] = []
        self.removed: list[str] = []
        self.volumes: list[str] = []

    def run(self, argv, stdout_path, stderr_path, timeout_s, name, append_stdout=False):
        """Record the argv; write the next scripted output to stdout_path; return the next exit code."""
        self.calls.append(("run", (list(argv), stdout_path, stderr_path, timeout_s, name), {}))
        self.argvs.append(list(argv))
        if stdout_path:
            text = self.outputs.pop(0) if self.outputs else ""
            with open(stdout_path, "a" if append_stdout else "w") as f:
                f.write(text)
        return self.exit_codes.pop(0) if self.exit_codes else 0

    def run_step(self, *args, **kwargs):
        """Record a step container run; return the next scripted exit code (default 0)."""
        self.calls.append(("run_step", args, kwargs))
        return self.exit_codes.pop(0) if self.exit_codes else 0

    def rm(self, name):
        """Record a container removal."""
        self.calls.append(("rm", (name,), {}))
        self.removed.append(name)

    def ps_ids(self, label):
        """Return the scripted leftover container ids."""
        self.calls.append(("ps_ids", (label,), {}))
        return list(self.orphans)

    def volume_create(self, name, labels):
        """Record a volume creation."""
        self.calls.append(("volume_create", (name, list(labels)), {}))
        self.volumes.append(name)

    def volume_rm(self, name):
        """Record a volume removal."""
        self.calls.append(("volume_rm", (name,), {}))
        if name in self.volumes:
            self.volumes.remove(name)

    def chown(self, path, uid, gid):
        """Record a chown."""
        self.calls.append(("chown", (str(path), uid, gid), {}))


class FakeClaude:
    """Skeleton claude: records calls and returns scripted sessions (step 09 will add the real method names)."""

    def __init__(self):
        """Start with no calls and no scripted sessions."""
        self.calls: list[tuple[str, tuple, dict]] = []
        self.sessions: list[dict] = []
        self.probes: list[str] = []

    def probe(self):
        """Answer a "can I use Claude again?" check with the next scripted kind (default ok)."""
        from phoenix9.claude import Result
        return Result(kind=self.probes.pop(0) if self.probes else "ok")

    def run_session(self, *args, **kwargs):
        """Record a session; write any scripted files and return the next scripted result."""
        self.calls.append(("run_session", args, kwargs))
        session = self.sessions.pop(0) if self.sessions else {}
        for name, text in (session.get("files") or {}).items():
            path = Path(kwargs.get("worktree", ".")) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return session.get("result", {})


    def launch(self, docker, **kwargs):
        """Record a launch; write scripted files into the workspace; return a Result of the scripted kind."""
        from phoenix9.claude import Result
        self.calls.append(("launch", (), kwargs))
        session = self.sessions.pop(0) if self.sessions else {}
        for name, text in (session.get("files") or {}).items():
            if name.startswith("/"):       # an absolute name is written through the mount that has this dst
                mount = [m for m in kwargs.get("extra_mounts", ()) if m.dst == str(Path(name).parent)][0]
                path = Path(mount.src) / Path(name).name
            elif kwargs.get("workspace_ro"):
                raise PermissionError(f"the workspace is read-only: cannot write {name}")
            else:
                path = Path(kwargs["workspace"]) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return Result(kind=session.get("kind", "ok"), text=session.get("text", ""),
                      cost_usd=session.get("cost_usd", 0.0), model=kwargs["ai"].get("model", ""))


def fake_adapters(tmp_path) -> Adapters:
    """Build the full fake set. Git is the real git adapter (real git runs on temp repos)."""
    return Adapters(docker=FakeDocker(), claude=FakeClaude(), git=Git(), host=FakeHost(),
                    http=FakeHttp(), clock=FakeClock(), notify=FakeNotify(), chat=FakeChat())
