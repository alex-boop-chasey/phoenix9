"""Neon: make a Neon project named after the project and read its pooled and direct connection strings."""
from urllib.parse import quote

from phoenix9.keymaker import Refused

MAKES = ("DATABASE_URL",)       # the status follows the pooled string; the direct string and id come with it
REGION = "aws-ap-southeast-2"


def _refused(status: int, body) -> Refused:
    """Plain words for a refused create (the reply is only looked at, never repeated)."""
    message = body.get("message") if isinstance(body, dict) else ""
    if 400 <= status < 500 and isinstance(message, str) and "limit" in message.lower() \
            and "project" in message.lower():
        return Refused("Neon refused: your plan has no room for another project.")
    if status in (401, 403):
        return Refused("Neon refused: the saved key can't make projects (needs: create projects).")
    return Refused(f"Neon did not make the project (answer {status}).")


def _pooler_host(params: dict) -> str:
    """The pooled host: pooler_host when Neon gives it, else the endpoint host with -pooler after the endpoint id."""
    given = params.get("pooler_host")
    if isinstance(given, str) and given:
        return given
    host = params.get("host")
    if not isinstance(host, str) or "." not in host:
        raise Refused("Neon made the project but sent no host back.")
    endpoint, _, rest = host.partition(".")
    if endpoint.endswith("-pooler"):
        return host
    return f"{endpoint}-pooler.{rest}"


def _pooled(params) -> str:
    """postgresql://role:password@pooler-host/database?sslmode=require from the connection parameters."""
    if not isinstance(params, dict):
        raise Refused("Neon made the project but sent no connection details back.")
    parts = [params.get(k) for k in ("role", "password", "database")]
    if not all(isinstance(p, str) and p for p in parts):
        raise Refused("Neon made the project but sent no connection details back.")
    role, password, database = (quote(p, safe="") for p in parts)
    return f"postgresql://{role}:{password}@{_pooler_host(params)}/{database}?sslmode=require"


def make(call, ctx) -> dict:
    """Returns DATABASE_URL (pooled), DATABASE_URL_UNPOOLED (direct) and NEON_PROJECT_ID.

    When the project already has either connection string saved, no second Neon project is made."""
    saved = [n for n in ("DATABASE_URL", "DATABASE_URL_UNPOOLED") if n in ctx["have"]]
    if saved:
        raise Refused(f"Neon: {saved[0]} is already saved, so Phoenix won't make a second database. "
                      "Paste the other connection string of the same database into Project > Settings > Keys.")
    project = {"name": ctx["project"], "region_id": (ctx["settings"].get("default_region") or "").strip() or REGION}
    org = (ctx["settings"].get("organisation") or "").strip()
    if org:
        project["org_id"] = org
    status, body = call("POST", "/api/v2/projects", {"project": project})
    if status not in (200, 201):
        raise _refused(status, body)
    made = body.get("project") if isinstance(body, dict) else None
    uris = body.get("connection_uris") if isinstance(body, dict) else None
    project_id = made.get("id") if isinstance(made, dict) else None
    first = uris[0] if isinstance(uris, list) and uris and isinstance(uris[0], dict) else {}
    direct = first.get("connection_uri")
    if not isinstance(project_id, str) or not project_id or not isinstance(direct, str) or not direct:
        raise Refused("Neon made the project but sent no connection string back.")
    return {"DATABASE_URL": _pooled(first.get("connection_parameters")), "DATABASE_URL_UNPOOLED": direct,
            "NEON_PROJECT_ID": project_id, "note": f"Made Neon project {ctx['project']}."}
