"""The dashboard's door to the new agent service: pass one call on and give back its reply."""
import json

from phoenix9 import agentnext
from phoenix9.ops import common


def call(method: str, path: str, body: bytes | None, headers: dict):
    """Send the call to the agent service; its reply (status, content_type, chunks), or Unavailable in plain words."""
    try:
        return common.make_adapters().agentnext.request(method, path, body, headers)
    except agentnext.AgentUnavailable as err:
        raise common.Unavailable(str(err)) from None


def tell_no_key(raw: bytes) -> bytes:
    """The /status body, with a plain `message` added when the service says it has no API key."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(data, dict) and data.get("key_present") is False:
        data["message"] = agentnext.NO_KEY
        return json.dumps(data).encode()
    return raw
