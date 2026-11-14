"""The adapter for the new agent service: calls it with the shared token and hands back its reply as it arrives."""
import json
import urllib.error
import urllib.request

from phoenix9 import settings

DEFAULT_URL = "http://127.0.0.1:8097"
DEFAULT_TOKEN_FILE = "/var/lib/phoenix9/agentkit/token"
CHUNK = 8192
TIMEOUT = 30
NOT_SET_UP = "The agent isn't set up yet: its token file can't be read."
NOT_RUNNING = "The new agent isn't running. Start phoenix-agentkit (see deploy/agentkit/README.md)."
NO_KEY = "The new agent has no API key yet. See deploy/agentkit/README.md."


class AgentUnavailable(Exception):
    """The agent service can't be reached or its token can't be read (the message is plain English)."""


class Reply:
    """An answer from the agent service: status, content type and the body as an iterator of byte chunks."""

    def __init__(self, status: int, content_type: str, chunks):
        self.status, self.content_type, self.chunks = status, content_type, chunks


class AgentNext:
    """Talks to the agent service at [agent_next] url, adding `Authorization: Bearer` from [agent_next] token_file."""

    def __init__(self, config: dict | None = None):
        """Take the settings from global.toml [agent_next] unless a dict is given."""
        table = config if config is not None else settings.read_global().get("agent_next")
        self.set_up = isinstance(table, dict)   # False when global.toml has no [agent_next] table
        table = table if isinstance(table, dict) else {}
        self.url = str(table.get("url") or DEFAULT_URL).rstrip("/")
        self.token_file = str(table.get("token_file") or DEFAULT_TOKEN_FILE)

    def token(self) -> str:
        """The shared token, read from its file on each call."""
        try:
            with open(self.token_file, encoding="utf-8") as f:
                value = f.read().strip()
        except OSError:
            raise AgentUnavailable(NOT_SET_UP) from None
        if not value:
            raise AgentUnavailable(NOT_SET_UP)
        return value

    def get_json(self, path: str) -> dict:
        """GET a path and return its JSON object; raises AgentUnavailable when the answer is not a good JSON object."""
        reply = self.request("GET", path)
        body = b"".join(reply.chunks)
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if reply.status != 200 or not isinstance(data, dict):
            raise AgentUnavailable("The new agent answered, but not in a way Phoenix understands.")
        return data

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                timeout: float | None = None) -> Reply:
        """Send one call (path includes any query) and return the reply; the body streams until it is read.
        timeout (seconds) replaces the usual TIMEOUT when given."""
        token = self.token()
        sent = dict(headers or {})
        sent["Authorization"] = "Bearer " + token
        if timeout is None:
            return self.send(method, self.url + path, sent, body)
        return self.send(method, self.url + path, sent, body, timeout=timeout)

    def send(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float = TIMEOUT) -> Reply:
        """Make the HTTP call (the one place that touches the network; tests replace it)."""
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            resp = err
        except (urllib.error.URLError, OSError):
            raise AgentUnavailable(NOT_RUNNING) from None
        kind = resp.headers.get("Content-Type", "application/octet-stream")
        return Reply(resp.status, kind, _chunks(resp))


def _chunks(resp):
    """The bytes of a response as they arrive (closes it at the end)."""
    try:
        while True:
            data = resp.read1(CHUNK) if hasattr(resp, "read1") else resp.read(CHUNK)
            if not data:
                return
            yield data
    finally:
        resp.close()
