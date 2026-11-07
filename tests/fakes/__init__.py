"""Fake adapters for tests: nothing here touches the real server."""
import os
import shutil
import subprocess
from pathlib import Path

from phoenix9.adapters import Adapters, Git


CANNED_PRS = [
    {"number": 7, "title": "Add search", "state": "OPEN", "isDraft": False, "url": "https://github.com/o/r/pull/7",
     "updatedAt": "2026-11-07T10:00:00Z", "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED"}]},
    {"number": 8, "title": "WIP", "state": "OPEN", "isDraft": True, "url": "https://github.com/o/r/pull/8",
     "updatedAt": "2026-11-06T10:00:00Z", "statusCheckRollup": []}]


class FakeHost:
    """Scripted host: responses chosen by argv prefix; every call is recorded."""

    def __init__(self):
        """Start with no scripted responses."""
        self.calls: list[list[str]] = []
        self.responses: list[tuple[list[str], tuple[int, str, str]]] = []
        self.sizes: dict[str, int] = {}
        self.files: dict[str, str] = {}      # host files (read_text / write_text), by path
        self.cwds: list = []                 # the cwd of each run() call, in step with .calls
        self.dirs: dict[str, list[str]] = {}  # folder listings, by path
        self.pids: set[int] = set()          # process ids that are alive
        self.stats: dict[str, dict] = {}     # {mode, uid} by path
        self.realpaths: dict[str, str] = {}  # symlinked path -> where it really points
        self.peer_uid: int | None = 0        # who owns the far end of every API connection (root unless set)
        self.socket_lookups: list = []       # (local, remote) of each socket_uid() call
        self.parents: dict[int, int] = {}    # pid -> parent pid
        self.stopped: list[int] = []         # pids sent SIGTERM through stop_pid()
        self.programs: dict[str, list[int]] = {}  # program name -> uids of its running processes
        self.proc_cwds: list[dict] = []      # running processes as {pid, name, cwd} (process_cwds())

    def script(self, prefix: list[str], rc: int = 0, out: str = "", err: str = "") -> None:
        """Answer any command starting with prefix (later scripts win)."""
        self.responses.append((list(prefix), (rc, out, err)))

    def script_seq(self, prefix: list[str], answers: list[tuple[int, str, str]]) -> None:
        """Answer commands starting with prefix with these (rc, out, err) in turn; the last one repeats."""
        self.responses.append((list(prefix), [tuple(a) for a in answers]))

    def run(self, argv, timeout=60, cwd=None):
        """Record the call and return the scripted answer (default: success, no output)."""
        argv = list(argv)
        self.calls.append(argv)
        self.cwds.append(str(cwd) if cwd else None)
        for prefix, answer in reversed(self.responses):
            if argv[:len(prefix)] == prefix:
                if isinstance(answer, list):      # a sequence from script_seq
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        return 0, "", ""

    def systemctl(self, *args):
        """Same as run(['systemctl', ...])."""
        return self.run(["systemctl", *args])

    def script_prs(self, items: list | None = None, rc: int = 0) -> None:
        """Answer `gh pr list` with these pull requests (gh's JSON shape), or fail with rc."""
        import json
        self.script(["gh", "pr", "list"], rc, json.dumps(items if items is not None else CANNED_PRS))

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

    def list_dir(self, path):
        """Names in .dirs[path], else the direct children of path seen in .files ([] when none)."""
        p = str(path).rstrip("/")
        if p in self.dirs:
            return list(self.dirs[p])
        names = {f[len(p) + 1:].split("/")[0] for f in self.files if f.startswith(p + "/")}
        return sorted(names)

    def exists(self, path):
        """True for a file in .files, a folder in .dirs or a path in .stats."""
        p = str(path)
        return p in self.files or p in self.dirs or p in self.stats or bool(self.list_dir(p))

    def pid_alive(self, pid):
        """True when the pid is in .pids."""
        return pid in self.pids

    def stop_pid(self, pid):
        """Record the pid as stopped and drop it from .pids."""
        self.stopped.append(pid)
        self.pids.discard(pid)

    def socket_uid(self, local, remote, tables=None):
        """The scripted .peer_uid for any socket (the lookup is recorded)."""
        self.socket_lookups.append((tuple(local), tuple(remote)))
        return self.peer_uid

    def program_uids(self, name, proc=None):
        """The uids scripted in .programs for a program name ([] when not running)."""
        return sorted(set(self.programs.get(name, [])))

    def process_cwds(self):
        """The processes set in .proc_cwds."""
        return list(self.proc_cwds)

    def parent_pid(self, pid):
        """The parent from .parents (None when not set)."""
        return self.parents.get(pid)

    def realpath(self, path):
        """The path from .realpaths, else the path itself (no symlinks unless scripted)."""
        return self.realpaths.get(str(path), str(path))

    def stat(self, path):
        """Return the {mode, uid} set in .stats (None when absent)."""
        return self.stats.get(str(path))

    def read_lines(self, path):
        """Lines of a file in .files ([] when absent)."""
        return self.files.get(str(path), "").splitlines(keepends=True)

    def _guard(self, path):
        """Refuse to delete anything outside the test's own Phoenix folders."""
        roots = [os.environ.get(k) for k in ("PHOENIX_HOME", "PHOENIX_PROJECTS", "PHOENIX_DELETED")]
        real = os.path.realpath(path)
        if not any(r and real.startswith(os.path.realpath(r) + os.sep) for r in roots):
            raise AssertionError(f"test tried to delete outside its temp folders: {path}")

    def remove_tree(self, path):
        """Really delete a folder, but only inside the test's temp Phoenix folders."""
        self._guard(path)
        self.calls.append(["remove_tree", str(path)])
        shutil.rmtree(path, ignore_errors=True)

    def remove_file(self, path):
        """Really delete a file, but only inside the test's temp Phoenix folders."""
        self._guard(path)
        self.calls.append(["remove_file", str(path)])
        Path(path).unlink(missing_ok=True)

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
        self.answer_with = None     # optional f(gate, answer, note, who) that answers through the CLI instead
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
            if self.answer_with:
                self.answer_with(gate, "acknowledged", self.note, "chat:delegate")
            else:
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
        self.images: dict[str, dict] = {}        # tag -> labels (an image that "exists")
        self.build_codes: list[int] = []         # exit codes for build(), in turn (default 0)
        self.ids: dict[str, str] = {}            # tag -> image id (default sha256:fake-<tag> for an image that exists)

    def image_exists(self, tag):
        """True when the tag is in .images."""
        self.calls.append(("image_exists", (tag,), {}))
        return tag in self.images

    def image_id(self, tag):
        """The exact id of a fake image ('' when it does not exist)."""
        self.calls.append(("image_id", (tag,), {}))
        if tag not in self.images:
            return ""
        return self.ids.get(tag, f"sha256:fake-{tag}")

    def image_label(self, tag, label):
        """The label set on a fake image ('' when absent)."""
        return str(self.images.get(tag, {}).get(label, ""))

    def build(self, dockerfile, tag, context, labels, log_path, timeout_s=0):
        """Record a build; on success the tag exists with these labels."""
        self.calls.append(("build", (str(dockerfile), tag, str(context), dict(labels)), {}))
        rc = self.build_codes.pop(0) if self.build_codes else 0
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(f"fake build of {tag}: exit {rc}\n")
        if rc == 0:
            self.images[tag] = dict(labels)
        return rc

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

    def bridge_gateway(self):
        """The fake Docker bridge gateway address."""
        self.calls.append(("bridge_gateway", (), {}))
        return "172.17.0.1"

    def bridge_info(self):
        """The fake Docker bridge: gateway, subnet and interface."""
        self.calls.append(("bridge_info", (), {}))
        return {"gateway": "172.17.0.1", "subnet": "172.17.0.0/16", "interface": "docker0"}

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


class RealCheckDocker(FakeDocker):
    """A fake docker whose check containers really run the command, in the mounted /workspace.

    `script_check(match, rc, files)` overrides one command: when the command contains `match` the
    container is not run; it returns `rc` and writes `files` ({name: text}) into the mounted /out.
    Scripts are used in order, `times` times each (None = every time), before any real run.
    """

    def __init__(self):
        """Start with no scripted check results."""
        super().__init__()
        self.scripts: list[dict] = []

    def script_check(self, match: str, rc: int = 0, files: dict | None = None, output: str = "", times=None):
        """Answer any check command containing `match` with this exit code, output and /out files."""
        self.scripts.append({"match": match, "rc": rc, "files": files or {}, "output": output, "times": times})

    @staticmethod
    def _mounts(argv) -> list[str]:
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]

    @staticmethod
    def _src(mount: str) -> str:
        return mount.split("src=")[1].split(",")[0]

    def _scripted(self, command, mounts):
        """The scripted (rc, output) for this command, after writing its files to /out; else None."""
        for s in self.scripts:
            if s["match"] in command and s["times"] != 0:
                if s["times"] is not None:
                    s["times"] -= 1
                for m in mounts:
                    if "dst=/out" in m:
                        for name, text in s["files"].items():
                            (Path(self._src(m)) / name).write_text(text)
                return s["rc"], s["output"]
        return None

    def run(self, argv, stdout_path, stderr_path, timeout_s, name, append_stdout=False):
        """Run the `bash -c` command from the argv in the worktree and return its real exit code."""
        self.argvs.append(list(argv))
        mounts = self._mounts(argv)
        workspace = next(self._src(m) for m in mounts if "dst=/workspace" in m)
        command = argv[-1]
        scripted = self._scripted(command, mounts)
        if scripted is not None:
            Path(stdout_path).write_text(scripted[1])
            return scripted[0]
        for m in mounts:   # a mounted /out is really a host folder here
            if "dst=/out" in m:
                command = command.replace("/out/", self._src(m) + "/")
        env = {**os.environ, **{kv.split("=", 1)[0]: kv.split("=", 1)[1] for kv in
                                (argv[i + 1] for i, a in enumerate(argv) if a == "-e") if "=" in kv}}
        p = subprocess.run(["bash", "-c", command], cwd=workspace, capture_output=True, text=True, env=env)
        Path(stdout_path).write_text(p.stdout + p.stderr)
        return p.returncode


class FakeClaude:
    """Skeleton claude: records calls and returns scripted sessions (step 09 will add the real method names)."""

    def __init__(self):
        """Start with no calls and no scripted sessions."""
        self.calls: list[tuple[str, tuple, dict]] = []
        self.sessions: list[dict] = []
        self.scripts: dict[tuple, list[dict]] = {}   # (role, task, attempt) -> sessions, None = any
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


    def script(self, role, task=None, attempt=None, **session):
        """Script the session for a role (builder, reviewer...), optionally for one task and attempt.

        The session is {files, kind, text, cost_usd}; file names starting with / go through a mount
        (e.g. /out/verdict.json); `{run_id}` in a file name becomes the launch's run id.
        Several scripts for one key are used one per launch (the last repeats).
        """
        self.scripts.setdefault((role, task, attempt), []).append(session)

    def _next_session(self, kwargs) -> dict:
        """The scripted session for this launch: most specific key first, then the plain FIFO list."""
        role, task, attempt = kwargs.get("role"), kwargs.get("task"), kwargs.get("attempt")
        for key in ((role, task, attempt), (role, task, None), (role, None, attempt), (role, None, None)):
            queue = self.scripts.get(key)
            if queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return self.sessions.pop(0) if self.sessions else {}

    def launch(self, docker, **kwargs):
        """Record a launch; write scripted files into the workspace; return a Result of the scripted kind."""
        from phoenix9.claude import Result
        self.calls.append(("launch", (), kwargs))
        session = self._next_session(kwargs)
        for name, text in (session.get("files") or {}).items():
            name = name.replace("{run_id}", str(kwargs.get("run_id", "")))
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


class FakeProxyHandle:
    """What FakeProxyFactory.start returns: a fake address and token, and a stop() that is recorded."""

    def __init__(self, factory: "FakeProxyFactory", service: str):
        """Point at http://proxy.fake/<service> with the factory's fixed token."""
        self._factory = factory
        self.service = service
        self.url = f"http://proxy.fake/{service}"
        self.token = FakeProxyFactory.TOKEN
        self.port = 40000 + len(factory.handles)
        self.stopped = False

    def stop(self):
        """Record the stop (safe to call twice; only the first is recorded)."""
        if not self.stopped:
            self.stopped = True
            self._factory.stopped.append(self.service)


class FakeProxyFactory:
    """Fake proxy adapter: records each start (never the key itself: only its length) and each stop.

    Nothing listens anywhere; tests script the fake http adapter at the returned url, e.g.
    `adapters.http.script("GET", "http://proxy.fake/supabase/v1/projects", 200, body=b"[]")`.
    """

    TOKEN = "fake-proxy-token"

    def __init__(self):
        """Start with nothing started or stopped."""
        self.started: list[dict] = []
        self.stopped: list[str] = []
        self.handles: list[FakeProxyHandle] = []

    def start(self, spec, key, *, log_path=None, step="", bind="127.0.0.1"):
        """Record (service, rules, step, bind, key length) and return a fake handle."""
        self.started.append({"service": spec.service, "rules": tuple(spec.rules), "step": step, "bind": bind,
                             "log_path": str(log_path) if log_path else None,
                             "key_len": len(key or ""), "key_seen": bool(key)})
        handle = FakeProxyHandle(self, spec.service)
        self.handles.append(handle)
        return handle

    def running(self) -> list[str]:
        """Services whose fake proxy was started and not yet stopped."""
        return [h.service for h in self.handles if not h.stopped]


def fake_adapters(tmp_path) -> Adapters:
    """Build the full fake set. Git is the real git adapter (real git runs on temp repos)."""
    return Adapters(docker=FakeDocker(), claude=FakeClaude(), git=Git(), host=FakeHost(),
                    http=FakeHttp(), clock=FakeClock(), notify=FakeNotify(), chat=FakeChat(),
                    proxy=FakeProxyFactory())
