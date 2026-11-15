"""Cloudflare: make a token for one project (Pages: Edit on the account, DNS: Edit on its zone when set)."""
import re

from phoenix9.keymaker import Refused

MAKES = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
NEEDS = "make API tokens (Account API Tokens: Edit)"
ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


def _result(status: int, body, what: str):
    """The reply's `result`, or plain words when Cloudflare refused (never the reply itself)."""
    if status == 403:
        raise Refused(f"Cloudflare refused: the saved key can't make tokens (needs: {NEEDS}).")
    if status not in (200, 201) or not isinstance(body, dict) or body.get("result") is None:
        raise Refused(f"Cloudflare did not {what} (answer {status}).")
    return body["result"]


def _groups(call, account: str, names: list[str]) -> dict:
    """{permission group name: id} for the names wanted."""
    found = _result(*call("GET", f"/accounts/{account}/tokens/permission_groups"), "list its permission groups")
    ids = {g.get("name"): g.get("id") for g in found if isinstance(g, dict)} if isinstance(found, list) else {}
    lost = [n for n in names if not ids.get(n)]
    if lost:
        raise Refused(f"Cloudflare has no permission group called {lost[0]}.")
    return {n: ids[n] for n in names}


def make(call, ctx) -> dict:
    """Make token phoenix-<project>; returns CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID.

    When the project already has a token saved, no token is made: only the account id is given."""
    account = (ctx["settings"].get("account_id") or "").strip()
    if not account:
        raise Refused("Cloudflare: save your Account ID in Settings > Services > Cloudflare first.")
    if not ID.match(account):
        raise Refused("Cloudflare: the saved Account ID doesn't look right (letters and digits only).")
    if "CLOUDFLARE_API_TOKEN" in ctx["have"]:
        return {"CLOUDFLARE_ACCOUNT_ID": account, "note": "Kept the saved Cloudflare token; no new token was made."}
    zone = (ctx["keys"].get("CLOUDFLARE_ZONE_ID") or "").strip()
    if zone and not ID.match(zone):
        raise Refused("Cloudflare: the project's CLOUDFLARE_ZONE_ID doesn't look right (letters and digits only).")
    groups = _groups(call, account, ["Pages Write"] + (["DNS Write"] if zone else []))
    policies = [{"effect": "allow", "resources": {f"com.cloudflare.api.account.{account}": "*"},
                 "permission_groups": [{"id": groups["Pages Write"]}]}]
    if zone:
        policies.append({"effect": "allow", "resources": {f"com.cloudflare.api.account.zone.{zone}": "*"},
                         "permission_groups": [{"id": groups["DNS Write"]}]})
    name = f"phoenix-{ctx['project']}"
    made = _result(*call("POST", f"/accounts/{account}/tokens", {"name": name, "policies": policies}),
                   "make the token")
    value = made.get("value") if isinstance(made, dict) else None
    if not isinstance(value, str) or not value:
        raise Refused("Cloudflare made the token but sent no value back.")
    reach = "Pages and DNS on its domain" if zone else "Pages"
    return {"CLOUDFLARE_API_TOKEN": value, "CLOUDFLARE_ACCOUNT_ID": account,
            "note": f"Made Cloudflare token {name} ({reach})."}
