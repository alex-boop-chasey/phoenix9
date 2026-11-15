"""OpenRouter: make an API key for one project with the saved management key."""
from phoenix9.keymaker import Refused


def make(call, ctx) -> dict:
    """Returns OPENROUTER_API_KEY (key phoenix-<project>)."""
    name = f"phoenix-{ctx['project']}"
    status, body = call("POST", "/keys", {"name": name})
    if status in (401, 403):
        raise Refused("OpenRouter refused: the saved key can't make keys (needs: manage API keys (a management key)).")
    if status not in (200, 201) or not isinstance(body, dict):
        raise Refused(f"OpenRouter did not make the key (answer {status}).")
    key = body.get("key")
    if not isinstance(key, str) or not key:
        raise Refused("OpenRouter made the key but sent no value back.")
    return {"OPENROUTER_API_KEY": key,
            "note": f"Set a spending limit on key {name} at openrouter.ai if you want one."}
