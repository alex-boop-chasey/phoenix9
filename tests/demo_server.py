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
from fakes import FakeChat, FakeDocker, FakeHost, FakeHttp, FakeNotify  # noqa: E402
from fakes import FakeClaude  # noqa: E402

from phoenix9 import paths  # noqa: E402
from phoenix9.adapters import Adapters, Clock, Git  # noqa: E402

CHAT_ON = ("demo-site", "phoenix9")
GITHUB_ACCOUNTS = ("rebirth-wd", "alex-boop-chasey")


class DemoHost(FakeHost):
    """A fake host whose chat servers really turn on and off, so creating and stopping a project works."""

    def __init__(self):
        """Start with the chat servers of the demo projects on."""
        super().__init__()
        self.active = {f"claude-rc@{name}.service" for name in CHAT_ON}

    def systemctl(self, *args):
        """Answer is-active, start, stop and disable from the remembered set; the rest is scripted."""
        if args[:1] == ("is-active",):
            self.calls.append(["systemctl", *args])
            self.cwds.append(None)
            return (0 if args[-1] in self.active else 3), "", ""
        if args[:1] == ("start",):
            self.active.add(args[-1])
        elif args[:1] == ("stop",) or (args[:1] == ("disable",) and "--now" in args):
            self.active.discard(args[-1])
        return super().systemctl(*args)


def demo_host() -> FakeHost:
    """A scripted host: chat servers for two projects are on, GitHub is signed in, folders have sizes."""
    host = DemoHost()
    host.script(["gh", "auth", "status"], rc=0, out="Logged in to github.com")
    host.script(["gh", "api", "user", "--jq", ".login"], out=GITHUB_ACCOUNTS[1] + "\n")
    host.script(["gh", "api", "user/orgs", "--jq", ".[].login"], out=GITHUB_ACCOUNTS[0] + "\n")
    for number, name in enumerate(seed_demo.PROJECTS, start=1):
        host.sizes[str(paths.projects() / name)] = number * 4_200_000
    return host


def demo_adapters() -> Adapters:
    """The adapter set the demo server uses: fakes everywhere, a real clock and local git only."""
    return Adapters(docker=FakeDocker(), claude=FakeClaude(), git=Git(), host=demo_host(), http=FakeHttp(),
                    clock=Clock(), notify=FakeNotify(), chat=FakeChat())


def build_server(home: Path, projects: Path, port: int):
    """Seed the folders when they are empty, put the demo adapters in, and return the (not started) server."""
    from phoenix9.api import server
    from phoenix9.ops import common
    if seed_demo.is_empty(home) and seed_demo.is_empty(projects):
        seed_demo.seed(home, projects)
    os.environ["PHOENIX_HOME"], os.environ["PHOENIX_PROJECTS"] = str(home), str(projects)
    os.environ.setdefault("PHOENIX_CLAUDE_JSON", str(Path(home) / "claude.json"))
    adapters = demo_adapters()
    adapters.host.files[os.environ["PHOENIX_CLAUDE_JSON"]] = '{"projects": {}}'
    common.make_adapters = lambda: adapters
    return server.make_server(port)


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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
