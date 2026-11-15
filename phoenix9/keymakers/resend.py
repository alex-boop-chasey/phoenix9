"""Resend: make a sending-only key for one project, limited to its domain when Resend has verified it."""
from phoenix9.keymaker import Refused

MAKES = ("RESEND_API_KEY", "RESEND_FROM")


def _domain_id(call, domain: str) -> str:
    """The id of the verified Resend domain with this name ('' when none)."""
    status, body = call("GET", "/domains")
    if status in (401, 403):
        raise Refused("Resend refused: the saved key can't list domains (needs: full access (to make sending keys)).")
    if status != 200:
        raise Refused(f"Resend did not list your domains (answer {status}).")
    rows = body.get("data") if isinstance(body, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and str(row.get("name", "")).lower() == domain and row.get("status") == "verified":
            return str(row.get("id") or "")
    return ""


def make(call, ctx) -> dict:
    """Returns RESEND_API_KEY, and RESEND_FROM when the project has none and a from-address is known.

    When the project already has a key saved, no key is made: only the from-address is given."""
    own = (ctx["keys"].get("RESEND_FROM") or "").strip()
    sender = own or (ctx["settings"].get("send_from") or "").strip()
    if "RESEND_API_KEY" in ctx["have"]:
        if own or "RESEND_FROM" in ctx["have"]:
            return {}
        if not sender:
            raise Refused("Resend: save a Send from address in Settings > Services > Resend, "
                          "or paste RESEND_FROM into Project > Settings > Keys.")
        return {"RESEND_FROM": sender, "note": "Kept the saved Resend key; no new key was made."}
    domain = sender.rpartition("@")[2].strip().lower() if "@" in sender else ""
    body = {"name": f"phoenix-{ctx['project']}", "permission": "sending_access"}
    found = _domain_id(call, domain) if domain else ""
    note = ""
    if found:
        body["domain_id"] = found
    else:
        where = domain or "your sending domain"
        note = f"The key can send from any of your Resend domains: verify {where} in Resend to limit it."
    status, made = call("POST", "/api-keys", body)
    if status in (401, 403):
        raise Refused("Resend refused: the saved key can't make keys (needs: full access (to make sending keys)).")
    if status not in (200, 201) or not isinstance(made, dict):
        raise Refused(f"Resend did not make the key (answer {status}).")
    token = made.get("token")
    if not isinstance(token, str) or not token:
        raise Refused("Resend made the key but sent no value back.")
    out = {"RESEND_API_KEY": token}
    if not own and sender:
        out["RESEND_FROM"] = sender
    if note:
        out["note"] = note
    return out
