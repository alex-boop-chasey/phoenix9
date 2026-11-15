"""Sentry: make (or reuse) a Sentry project named after the project and read its public DSN."""
import re

from phoenix9.keymaker import Refused

MAKES = ("PUBLIC_SENTRY_DSN",)       # the status follows the DSN; the org and project slugs are filled alongside
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$", re.IGNORECASE)


def _setting(ctx, name: str, label: str) -> str:
    """A required account setting, or a plain refusal naming it."""
    value = (ctx["settings"].get(name) or "").strip()
    if not value:
        raise Refused(f"Sentry: save your {label} in Settings > Services > Sentry first.")
    if not SLUG.match(value):
        raise Refused(f"Sentry: the saved {label} doesn't look like a slug.")
    return value


def _dsn(keys) -> str:
    """The first active key's public DSN ('' when there is none)."""
    for key in keys if isinstance(keys, list) else []:
        if isinstance(key, dict) and key.get("isActive", True) and isinstance(key.get("dsn"), dict):
            public = key["dsn"].get("public")
            if isinstance(public, str) and public:
                return public
    return ""


def make(call, ctx) -> dict:
    """Returns PUBLIC_SENTRY_DSN, SENTRY_ORG and SENTRY_PROJECT."""
    org = _setting(ctx, "organisation", "organisation slug")
    team = _setting(ctx, "default_team", "default team")
    slug = ctx["project"]
    if not SLUG.match(slug):
        raise Refused("Sentry: the project name can't be used as a Sentry project slug.")
    created, _ = call("POST", f"/teams/{org}/{team}/projects/", {"name": slug, "slug": slug})
    if created in (401, 403):
        raise Refused("Sentry refused: the saved key can't create projects (needs: create projects (project:write)).")
    if created not in (200, 201, 409):
        raise Refused(f"Sentry did not make the project (answer {created}).")
    status, keys = call("GET", f"/projects/{org}/{slug}/keys/")
    if status != 200:
        raise Refused(f"Sentry did not list the project's keys (answer {status}).")
    dsn = _dsn(keys)
    if not dsn:
        raise Refused(f"Sentry project {slug} has no active client key.")
    note = f"Used the existing Sentry project {slug}" if created == 409 else f"Made Sentry project {slug}"
    return {"PUBLIC_SENTRY_DSN": dsn, "SENTRY_ORG": org, "SENTRY_PROJECT": slug, "note": note}
