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

    def script(self, prefix: list[str], rc: int = 0, out: str = "", err: str = "") -> None:
        """Answer any command starting with prefix (later scripts win)."""
        self.responses.append((list(prefix), (rc, out, err)))

    def run(self, argv, timeout=60):
        """Record the call and return the scripted answer (default: success, no output)."""
        argv = list(argv)
        self.calls.append(argv)
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

    def du_bytes(self, path):
        """Return the size set in .sizes (default 0)."""
        self.calls.append(["du_bytes", str(path)])
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
    """Records delegate requests."""

    def __init__(self):
        """Start empty."""
        self.calls: list[tuple] = []
        self.result = None

    def delegate(self, *args, **kwargs):
        """Record the request and return the scripted result."""
        self.calls.append((args, kwargs))
        return self.result


class FakeDocker:
    """Skeleton docker: records calls and returns scripted results (step 08 will add the real method names)."""

    def __init__(self):
        """Start with no calls and a default exit code of 0."""
        self.calls: list[tuple[str, tuple, dict]] = []
        self.exit_codes: list[int] = []

    def run_step(self, *args, **kwargs):
        """Record a step container run; return the next scripted exit code (default 0)."""
        self.calls.append(("run_step", args, kwargs))
        return self.exit_codes.pop(0) if self.exit_codes else 0


class FakeClaude:
    """Skeleton claude: records calls and returns scripted sessions (step 09 will add the real method names)."""

    def __init__(self):
        """Start with no calls and no scripted sessions."""
        self.calls: list[tuple[str, tuple, dict]] = []
        self.sessions: list[dict] = []

    def run_session(self, *args, **kwargs):
        """Record a session; write any scripted files and return the next scripted result."""
        self.calls.append(("run_session", args, kwargs))
        session = self.sessions.pop(0) if self.sessions else {}
        for name, text in (session.get("files") or {}).items():
            path = Path(kwargs.get("worktree", ".")) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return session.get("result", {})


def fake_adapters(tmp_path) -> Adapters:
    """Build the full fake set. Git is the real git adapter (real git runs on temp repos)."""
    return Adapters(docker=FakeDocker(), claude=FakeClaude(), git=Git(), host=FakeHost(),
                    http=FakeHttp(), clock=FakeClock(), notify=FakeNotify(), chat=FakeChat())
