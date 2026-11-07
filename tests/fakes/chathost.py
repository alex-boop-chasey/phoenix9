"""A fake host for project chat tests: the chat unit comes up on enable (or refuses), with a registry entry."""
import json

from fakes import FakeClock, FakeHost

HOME = "/root/.claude"
SOCK = "/tmp/cc-socks-0/a.sock"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
BRIDGE = "session_BBB_2"


class ChatHost(FakeHost):
    """mode 'ok': enabling the unit starts it and the conversation appears; 'fail': systemctl enable fails."""

    def __init__(self, mode, folder, claude_json):
        super().__init__()
        self.mode, self.folder, self.unit = mode, folder, "inactive"
        self.files[str(claude_json)] = json.dumps({"projects": {}})

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit == "active" else "0\n"), ""
        if args[0] == "enable":
            if self.mode == "fail":
                return 1, "", "boom"
            self.unit = "active"
        return 0, "", ""

    def add_session(self):
        data = {"pid": 10, "cwd": str(self.folder), "name": "x", "status": "idle", "messagingSocketPath": SOCK,
                "kind": "interactive", "sessionId": SID, "startedAt": 1, "bridgeSessionId": BRIDGE}
        self.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        self.files[SOCK] = ""
        self.pids.update({100, 10})
        self.parents[10] = 100


class ChatClock(FakeClock):
    """A clock whose first sleep makes the conversation appear when the host works."""

    def __init__(self, host):
        super().__init__()
        self.host = host

    def sleep(self, s):
        super().sleep(s)
        if self.host.mode == "ok":
            self.host.add_session()


def chat_adapters(tmp_path, mode, folder, claude_json):
    """Fake adapters whose host and clock behave as above."""
    from fakes import fake_adapters
    a = fake_adapters(tmp_path)
    a.host = ChatHost(mode, folder, claude_json)
    a.clock = ChatClock(a.host)
    return a
