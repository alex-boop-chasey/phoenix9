"""The dashboard's door to the new agent service: pass one call on and give back its reply."""
from phoenix9 import agentnext
from phoenix9.ops import common


def call(method: str, path: str, body: bytes | None, headers: dict):
    """Send the call to the agent service; its reply (status, content_type, chunks), or Unavailable in plain words."""
    try:
        return common.make_adapters().agentnext.request(method, path, body, headers)
    except agentnext.AgentUnavailable as err:
        raise common.Unavailable(str(err)) from None
