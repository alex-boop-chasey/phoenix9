"""Key makers for Cloudflare, Sentry and Resend: exact calls, values saved unseen, plain refusals, [proxy] unchanged."""
import dataclasses
import json
import secrets
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from phoenix9 import adapters as adapters_mod, keymaker, keys, paths, proxy, services
from phoenix9.ops import common

REPO = Path(__file__).resolve().parent.parent
ACCOUNT = "0123456789abcdef0123456789abcdef"
ZONE = "fedcba9876543210fedcba9876543210"


def _value(tag: str) -> str:
    """A made-up, high-entropy value built at run time."""
    return f"made-{tag}-{secrets.token_hex(12)}"


class Scripted:
    """A local upstream that answers (method, path) with scripted JSON and records every request."""

    def __init__(self):
        """Start serving; unscripted calls answer 404."""
        self.answers: dict = {}
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                path = self.path.partition("?")[0]
                outer.requests.append({"method": self.command, "path": path, "auth": self.headers.get("Authorization"),
                                       "body": json.loads(raw) if raw else None})
                status, body = outer.answers.get((self.command, path), (404, {"message": "not here"}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _any

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def asked(self) -> list[tuple]:
        """(method, path, body) of every request, in order."""
        return [(r["method"], r["path"], r["body"]) for r in self.requests]

    def close(self):
        """Stop the server."""
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream():
    """A scripted upstream for one test."""
    u = Scripted()
    yield u
    u.close()


@pytest.fixture
def real(upstream, monkeypatch):
    """Adapters with the real make proxy pointed at the local upstream, and real http."""
    started = []

    class LocalProxy:
        def start(self, spec, key, *, log_path, step, bind="127.0.0.1", ports=None):
            started.append(spec)
            local = dataclasses.replace(spec, upstream=upstream.url)
            return proxy.serve(local, key, log_path=Path(log_path), step=step, bind=bind,
                               allow_plain_http_upstream=True)

    fake = SimpleNamespace(proxy=LocalProxy(), http=adapters_mod.Http(), started=started)
    monkeypatch.setattr(common, "make_adapters", lambda: fake)
    return fake


def project(phoenix_env, *names: str) -> str:
    """Project demo using the named services."""
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "phoenix.toml").write_text(f"services = {json.dumps(list(names))}\n")
    return "demo"


def connect(name: str, settings: dict) -> str:
    """Save a made-up account key for the service and its settings; the key value."""
    svc = services.get(name)
    account = _value("account")
    keys.write_secret_file(svc["secrets_file"], {svc["make"]["key"]: account})
    reg = services.read_registry()
    reg[name] = {"connected": True, "settings": settings}
    services.write_registry(reg)
    return account


def everything_written() -> str:
    """Every file Phoenix wrote outside the key stores (logs, events, command records, registry)."""
    stores = {paths.secrets(), paths.keys()}
    return "".join(p.read_text(errors="replace") for p in paths.home().rglob("*")
                   if p.is_file() and not any(s in p.parents for s in stores))


def unseen(result: dict, *values: str):
    """No value appears in the result or in anything Phoenix wrote."""
    seen = json.dumps(result) + everything_written()
    for v in values:
        assert v not in seen


# ---------- Cloudflare ----------

GROUPS = {"result": [{"id": "g-pages", "name": "Pages Write"}, {"id": "g-dns", "name": "DNS Write"},
                     {"id": "g-other", "name": "Workers Scripts Write"}]}


def cloudflare(upstream, token: str):
    """Script Cloudflare's permission groups and token answers."""
    upstream.answers[("GET", f"/accounts/{ACCOUNT}/tokens/permission_groups")] = (200, GROUPS)
    upstream.answers[("POST", f"/accounts/{ACCOUNT}/tokens")] = (200, {"result": {"id": "t1", "value": token}})


def test_cloudflare_without_zone(phoenix_env, real, upstream):
    name = project(phoenix_env, "cloudflare")
    account = connect("cloudflare", {"account_id": ACCOUNT})
    token = _value("cf")
    cloudflare(upstream, token)
    result = keymaker.make(name, who="tester")
    assert result["saved"] == {"cloudflare": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]}
    assert upstream.asked() == [
        ("GET", f"/accounts/{ACCOUNT}/tokens/permission_groups", None),
        ("POST", f"/accounts/{ACCOUNT}/tokens", {"name": "phoenix-demo", "policies": [
            {"effect": "allow", "resources": {f"com.cloudflare.api.account.{ACCOUNT}": "*"},
             "permission_groups": [{"id": "g-pages"}]}]}),
    ]
    assert all(r["auth"] == f"Bearer {account}" for r in upstream.requests)
    assert keys.get_value(name, "CLOUDFLARE_API_TOKEN") == token
    assert keys.get_value(name, "CLOUDFLARE_ACCOUNT_ID") == ACCOUNT
    assert result["notes"]["cloudflare"] == "Made Cloudflare token phoenix-demo (Pages)."
    unseen(result, token, account)


def test_cloudflare_with_zone(phoenix_env, real, upstream):
    name = project(phoenix_env, "cloudflare")
    connect("cloudflare", {"account_id": ACCOUNT})
    keys.set_key(name, "CLOUDFLARE_ZONE_ID", ZONE, secret=False)
    token = _value("cf")
    cloudflare(upstream, token)
    result = keymaker.make(name, ["cloudflare"], who="tester")
    assert result["saved"] == {"cloudflare": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]}
    policies = upstream.requests[1]["body"]["policies"]
    assert policies[1] == {"effect": "allow", "resources": {f"com.cloudflare.api.account.zone.{ZONE}": "*"},
                           "permission_groups": [{"id": "g-dns"}]}
    assert len(policies) == 2 and policies[0]["permission_groups"] == [{"id": "g-pages"}]
    unseen(result, token)


def test_cloudflare_secret_zone_is_not_used(phoenix_env, real, upstream):
    name = project(phoenix_env, "cloudflare")
    connect("cloudflare", {"account_id": ACCOUNT})
    keys.set_key(name, "CLOUDFLARE_ZONE_ID", ZONE, secret=True)
    cloudflare(upstream, _value("cf"))
    keymaker.make(name, ["cloudflare"], who="tester")
    assert len(upstream.requests[1]["body"]["policies"]) == 1


def test_cloudflare_403_words(phoenix_env, real, upstream):
    name = project(phoenix_env, "cloudflare")
    connect("cloudflare", {"account_id": ACCOUNT})
    upstream.answers[("GET", f"/accounts/{ACCOUNT}/tokens/permission_groups")] = (403, {"success": False})
    result = keymaker.make(name, ["cloudflare"], who="tester")
    needs = services.get("cloudflare")["make"]["needs"]
    assert result["problems"]["cloudflare"] == f"Cloudflare refused: the saved key can't make tokens (needs: {needs})."
    assert result["saved"] == {} and keys.get_value(name, "CLOUDFLARE_API_TOKEN") in (None, "")


def test_cloudflare_without_account_id_refuses(phoenix_env, real, upstream):
    name = project(phoenix_env, "cloudflare")
    connect("cloudflare", {})
    result = keymaker.make(name, ["cloudflare"], who="tester")
    assert "Account ID" in result["problems"]["cloudflare"] and upstream.requests == []


# ---------- Sentry ----------

def sentry(upstream, created: int, dsn: str):
    """Script Sentry's project and keys answers."""
    upstream.answers[("POST", "/teams/acme/web/projects/")] = (created, {"slug": "demo"})
    upstream.answers[("GET", "/projects/acme/demo/keys/")] = (200, [
        {"isActive": False, "dsn": {"public": "https://old@o1.ingest.sentry.example/1"}},
        {"isActive": True, "dsn": {"public": dsn, "secret": _value("secret-dsn")}},
    ])


def test_sentry_makes_project(phoenix_env, real, upstream):
    name = project(phoenix_env, "sentry")
    account = connect("sentry", {"organisation": "acme", "default_team": "web"})
    dsn = f"https://{secrets.token_hex(8)}@o1.ingest.sentry.example/2"
    sentry(upstream, 201, dsn)
    result = keymaker.make(name, who="tester")
    assert upstream.asked() == [("POST", "/teams/acme/web/projects/", {"name": "demo", "slug": "demo"}),
                                ("GET", "/projects/acme/demo/keys/", None)]
    assert all(r["auth"] == f"Bearer {account}" for r in upstream.requests)
    assert result["saved"] == {"sentry": ["PUBLIC_SENTRY_DSN", "SENTRY_ORG", "SENTRY_PROJECT"]}
    assert keys.get_value(name, "PUBLIC_SENTRY_DSN") == dsn
    flags = {k["name"]: k["secret"] for k in keys.list_keys(name)}
    assert flags["SENTRY_ORG"] is False and flags["SENTRY_PROJECT"] is False
    assert keys.get_value(name, "SENTRY_ORG") == "acme" and keys.get_value(name, "SENTRY_PROJECT") == "demo"
    assert result["notes"]["sentry"] == "Made Sentry project demo"
    unseen(result, dsn, account)


def test_sentry_reuses_existing_project(phoenix_env, real, upstream):
    name = project(phoenix_env, "sentry")
    connect("sentry", {"organisation": "acme", "default_team": "web"})
    dsn = f"https://{secrets.token_hex(8)}@o1.ingest.sentry.example/2"
    sentry(upstream, 409, dsn)
    result = keymaker.make(name, ["sentry"], who="tester")
    assert result["notes"]["sentry"] == "Used the existing Sentry project demo"
    assert keys.get_value(name, "PUBLIC_SENTRY_DSN") == dsn


@pytest.mark.parametrize("settings, missing", [({"default_team": "web"}, "organisation slug"),
                                               ({"organisation": "acme"}, "default team")])
def test_sentry_missing_setting_refuses(phoenix_env, real, upstream, settings, missing):
    name = project(phoenix_env, "sentry")
    connect("sentry", settings)
    result = keymaker.make(name, ["sentry"], who="tester")
    assert result["problems"]["sentry"] == f"Sentry: save your {missing} in Settings > Services > Sentry first."
    assert upstream.requests == []


# ---------- Resend ----------

def resend(upstream, status: str, token: str):
    """Script Resend's domains and key answers."""
    upstream.answers[("GET", "/domains")] = (200, {"data": [
        {"id": "d-other", "name": "other.example", "status": "verified"},
        {"id": "d-mine", "name": "mine.example", "status": status}]})
    upstream.answers[("POST", "/api-keys")] = (201, {"id": "k1", "token": token})


def test_resend_verified_domain(phoenix_env, real, upstream):
    name = project(phoenix_env, "resend")
    account = connect("resend", {"send_from": "hello@mine.example"})
    token = _value("re")
    resend(upstream, "verified", token)
    result = keymaker.make(name, who="tester")
    assert upstream.asked() == [("GET", "/domains", None), ("POST", "/api-keys", {
        "name": "phoenix-demo", "permission": "sending_access", "domain_id": "d-mine"})]
    assert all(r["auth"] == f"Bearer {account}" for r in upstream.requests)
    assert result["saved"] == {"resend": ["RESEND_API_KEY", "RESEND_FROM"]}
    assert keys.get_value(name, "RESEND_API_KEY") == token
    assert keys.get_value(name, "RESEND_FROM") == "hello@mine.example"
    assert "resend" not in result["notes"]
    unseen(result, token, account)


def test_resend_not_verified_domain(phoenix_env, real, upstream):
    name = project(phoenix_env, "resend")
    connect("resend", {"send_from": "hello@other.example"})
    keys.set_key(name, "RESEND_FROM", "site@mine.example", secret=False)
    token = _value("re")
    resend(upstream, "pending", token)
    result = keymaker.make(name, who="tester")
    assert upstream.asked()[1] == ("POST", "/api-keys", {"name": "phoenix-demo", "permission": "sending_access"})
    assert result["saved"] == {"resend": ["RESEND_API_KEY"]}
    assert keys.get_value(name, "RESEND_FROM") == "site@mine.example"
    assert result["notes"]["resend"] == ("The key can send from any of your Resend domains: "
                                         "verify mine.example in Resend to limit it.")
    unseen(result, token)


# ---------- the step proxy is unchanged ----------

# The [proxy] rules as they were on main before any [make] block was added.
PROXY_ON_MAIN = {
    "cloudflare": [("GET", "/user/tokens/verify"), ("GET", "/accounts/*/tokens/verify"), ("GET", "/accounts"),
                   ("GET", "/accounts/*/pages/projects"), ("POST", "/accounts/*/pages/projects"),
                   ("GET", "/accounts/*/pages/projects/*"), ("GET", "/zones"), ("GET", "/zones/*/dns_records"),
                   ("POST", "/zones/*/dns_records")],
    "sentry": [("GET", "/organizations/"), ("GET", "/organizations/*/projects/"), ("POST", "/teams/*/*/projects/"),
               ("GET", "/projects/*/*/keys/")],
    "resend": [("GET", "/domains"), ("GET", "/domains/*")],
}
UPSTREAMS = {"cloudflare": "https://api.cloudflare.com/client/v4", "sentry": "https://sentry.io/api/0",
             "resend": "https://api.resend.com"}


@pytest.mark.parametrize("name", sorted(PROXY_ON_MAIN))
def test_proxy_sections_unchanged(name):
    data = tomllib.loads((REPO / "services" / name / "service.toml").read_text())
    block = data["proxy"]
    assert [(r["method"], r["path"]) for r in block["allow"]] == PROXY_ON_MAIN[name]
    assert block["upstream"] == UPSTREAMS[name] and block["auth_format"] == "Bearer {key}"
    svc = services.get(name)
    assert [(r.method, r.path) for r in proxy.spec_from_service(svc).rules] == PROXY_ON_MAIN[name]
    assert svc["make"] and keymaker._provider(name) is not None
    if name == "cloudflare":
        assert proxy.find_rule(proxy.spec_from_service(svc).rules, "POST", f"/accounts/{ACCOUNT}/tokens") is None
