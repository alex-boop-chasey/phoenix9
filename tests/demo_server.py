"""The dashboard API on demo data with fake adapters: nothing here touches systemd, GitHub, Docker or Claude.

    python3 tests/demo_server.py <home> <projects> --port N      (port 0 picks a free one)
"""
import argparse
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
for folder in (HERE.parent, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import seed_demo  # noqa: E402
from fakes import FakeDocker, FakeHost, FakeHttp, FakeNotify, FakeProxyFactory  # noqa: E402
from fakes import FakeClaude  # noqa: E402

from phoenix9 import paths  # noqa: E402
from phoenix9.adapters import Adapters, Clock, Git  # noqa: E402

GITHUB_ACCOUNTS = ("rebirth-wd", "alex-boop-chasey")


class DemoHost(FakeHost):
    """A scripted host that also reads the demo Claude folder from disk and says the demo agent is alive."""

    def __init__(self, claude_dir: Path | None = None):
        """Remember the demo Claude folder."""
        super().__init__()
        self.claude_dir = str(claude_dir) if claude_dir else None
        self.pids.add(seed_demo.AGENT_PID)

    def _mine(self, path) -> bool:
        """True when path is inside the demo Claude folder."""
        return bool(self.claude_dir) and str(path).startswith(self.claude_dir + "/")

    def read_text(self, path):
        """Read a demo Claude file from disk, else as the fake does."""
        return Path(path).read_text() if self._mine(path) else super().read_text(path)

    def read_lines(self, path):
        """Lines of a demo Claude file from disk, else as the fake does."""
        if not self._mine(path):
            return super().read_lines(path)
        try:
            return Path(path).read_text().splitlines(keepends=True)
        except OSError:
            return []

    def list_dir(self, path):
        """Names in a demo Claude folder from disk, else as the fake does."""
        if not self._mine(str(path) + "/"):
            return super().list_dir(path)
        try:
            return sorted(p.name for p in Path(path).iterdir())
        except OSError:
            return []

    def stat(self, path):
        """The mode, owner and mtime of a demo Claude file, else as the fake does."""
        if not self._mine(path):
            return super().stat(path)
        try:
            info = Path(path).stat()
        except OSError:
            return None
        return {"mode": info.st_mode & 0o777, "uid": info.st_uid, "mtime": info.st_mtime}

    def exists(self, path):
        """True for the demo agent's socket and for demo Claude files that exist."""
        if str(path) == seed_demo.AGENT_SOCKET:
            return True
        return Path(path).exists() if self._mine(path) else super().exists(path)


def demo_host(claude_dir: Path | None = None) -> FakeHost:
    """A scripted host: GitHub is signed in, folders have sizes, the demo agent is alive."""
    host = DemoHost(claude_dir)
    host.script(["gh", "auth", "status"], rc=0, out="Logged in to github.com")
    host.script(["gh", "api", "user", "--jq", ".login"], out=GITHUB_ACCOUNTS[1] + "\n")
    host.script(["gh", "api", "user/orgs", "--jq", ".[].login"], out=GITHUB_ACCOUNTS[0] + "\n")
    for number, name in enumerate(seed_demo.PROJECTS, start=1):
        host.sizes[str(paths.projects() / name)] = number * 4_200_000
    return host


def demo_adapters(claude_dir: Path | None = None) -> Adapters:
    """The adapter set the demo server uses: fakes everywhere, a real clock and local git only."""
    return Adapters(docker=FakeDocker(), claude=FakeClaude(), git=Git(), host=demo_host(claude_dir), http=FakeHttp(),
                    clock=Clock(), notify=FakeNotify(), proxy=FakeProxyFactory())


def move_run_on(gate: dict, action: str) -> None:
    """Demo only: change the run the way the runner would once a gate is answered."""
    from phoenix9 import runs, state
    folder = runs.find_run(gate["run"])
    if folder is None:
        return
    final = {"approve": "passed", "acknowledged": "running", "back": "running"}.get(action, "skipped")

    def change(st):
        for item in [*st.get("steps", []), *st.get("tasks", {}).values()]:
            if item["status"] == "waiting" or (item.get("gate") == gate["id"] and item["status"] == "failed"):
                item["status"] = final
        st["status"] = {"back": "running", "acknowledged": "running", "stop": "stopped"}.get(action, "done")
    state.update(folder, change)


def answering_moves_run(answer, home: str):
    """Wrap the gate answer so the demo run moves on afterwards, only while PHOENIX_HOME is the demo home."""
    def wrapped(gate_id, action, note="", who="cli", by=None):
        from phoenix9 import gates as core
        gate = next((g for g in core.list_gates(open_only=False) if g["id"] == gate_id), None)
        result = answer(gate_id, action, note, who, by)
        if gate is not None and os.environ.get("PHOENIX_HOME") == home:
            move_run_on(gate, action)
        return result
    return wrapped


REPLY = "Got it. I am looking at that now."
REPLY_AFTER = 1.0


def append_line(path: Path, line: str) -> int:
    """Add one line to a transcript file; returns how many lines it has now."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return len(path.read_text().splitlines())


def demo_send(text: str, context=None, who: str = "cli", panel: bool = False) -> dict:
    """Demo only: add the user's line to the demo transcript, and an agent reply a second later."""
    from datetime import datetime, timezone
    from phoenix9 import agentlink, settings
    path = Path(agentlink.transcript_path(agentlink.CLAUDE_HOME, settings.agent_settings()["folder"],
                                          seed_demo.AGENT_SESSION))
    stamp = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sid = seed_demo.AGENT_SESSION
    peer = {"origin": {"kind": "peer", "name": seed_demo.PANEL_PEER if panel else "Phoenix (%s)" % who}}
    after = len(path.read_text().splitlines())
    append_line(path, seed_demo._say("user", text, sid, stamp(), **peer))

    def reply():
        append_line(path, seed_demo._say("assistant", [{"type": "text", "text": REPLY}], sid, stamp()))
    timer = threading.Timer(REPLY_AFTER, reply)
    timer.daemon = True
    timer.start()
    return {"sent": True, "at": stamp(), "after_line": after}


def point_agentlink_at_demo(claude_dir: Path, host) -> callable:
    """Make the agent link (state, messages, the live stream, sending) use the demo Claude folder and demo host;
    returns a function that puts everything back."""
    from phoenix9 import agentlink
    from phoenix9.ops import agent as ops_agent
    old = {"home": agentlink.CLAUDE_HOME, "find": agentlink.find, "defaults": agentlink.status.__defaults__,
           "send": ops_agent.send}
    real_find = agentlink.find
    home = str(claude_dir)

    demo = host

    def find(home_dir=home, host=None):
        """The demo agent session (the demo host when none is given)."""
        return real_find(home_dir, host or demo)

    agentlink.CLAUDE_HOME = home
    agentlink.find = find
    agentlink.status.__defaults__ = (home, None)
    ops_agent.send = demo_send
    agentlink.forget()

    def restore():
        """Undo point_agentlink_at_demo."""
        agentlink.CLAUDE_HOME, agentlink.find = old["home"], old["find"]
        agentlink.status.__defaults__ = old["defaults"]
        ops_agent.send = old["send"]
    return restore


def build_server(home: Path, projects: Path, port: int):
    """Seed the folders when they are empty, put the demo adapters in, and return the (not started) server."""
    from phoenix9.api import server
    from phoenix9.ops import common
    if seed_demo.is_empty(home) and seed_demo.is_empty(projects):
        seed_demo.seed(home, projects)
    os.environ["PHOENIX_HOME"], os.environ["PHOENIX_PROJECTS"] = str(home), str(projects)
    os.environ["PHOENIX_INSTALL"] = str(Path(home) / "phoenix9-install")
    os.environ.setdefault("PHOENIX_CLAUDE_JSON", str(Path(home) / "claude.json"))
    adapters = demo_adapters(seed_demo.claude_home(home))
    adapters.host.files[os.environ["PHOENIX_CLAUDE_JSON"]] = '{"projects": {}}'
    common.make_adapters = lambda: adapters
    from phoenix9.ops import gates as ops_gates
    ops_gates.answer = answering_moves_run(ops_gates.answer, str(home))
    restore = point_agentlink_at_demo(seed_demo.claude_home(home), adapters.host)
    httpd = server.make_server(port)
    httpd.restore_agentlink = restore
    return httpd


def main(argv: list) -> int:
    """Run the demo server until stopped."""
    parser = argparse.ArgumentParser(description="Phoenix API on demo data with fake adapters")
    parser.add_argument("home")
    parser.add_argument("projects")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    try:
        httpd = build_server(Path(args.home), Path(args.projects), args.port)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    print(f"Phoenix API listening on http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
    try:
        while not httpd.stopping.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        httpd.stopping.set()
        httpd.shutdown()
        httpd.server_close()
        httpd.restore_agentlink()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
