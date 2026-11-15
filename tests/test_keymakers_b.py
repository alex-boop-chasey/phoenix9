"""Key makers for Neon and OpenRouter: exact calls, values saved unseen, plain refusals, [proxy] unchanged."""
import secrets
import tomllib
from pathlib import Path

import pytest

from phoenix9 import keymaker, keys, proxy, services
from test_keymakers_a import _value, connect, project, real, unseen, upstream  # noqa: F401 (fixtures)

REPO = Path(__file__).resolve().parent.parent
PROJECT_ID = "cool-lake-12345678"


def _params(host: str, password: str, pooler: str | None) -> dict:
    """Neon's connection_parameters, with or without pooler_host."""
    params = {"database": "neondb", "password": password, "role": "neondb_owner", "host": host}
    if pooler is not None:
        params["pooler_host"] = pooler
    return params


def neon(upstream, password: str, *, pooler: str | None):
    """Script Neon's create-project answer; the direct connection string."""
    host = "ep-quiet-sun-a1b2c3d4.ap-southeast-2.aws.neon.tech"
    direct = f"postgresql://neondb_owner:{password}@{host}/neondb?sslmode=require"
    upstream.answers[("POST", "/api/v2/projects")] = (201, {
        "project": {"id": PROJECT_ID, "name": "demo"},
        "connection_uris": [{"connection_uri": direct, "connection_parameters": _params(host, password, pooler)}],
    })
    return direct


# ---------- Neon ----------

def test_neon_body_without_organisation(phoenix_env, real, upstream):
    name = project(phoenix_env, "neon")
    account = connect("neon", {})
    password = secrets.token_hex(16)
    direct = neon(upstream, password, pooler=None)
    result = keymaker.make(name, who="tester")
    assert upstream.asked() == [("POST", "/api/v2/projects",
                                 {"project": {"name": "demo", "region_id": "aws-ap-southeast-2"}})]
    assert all(r["auth"] == f"Bearer {account}" for r in upstream.requests)
    assert result["saved"] == {"neon": ["DATABASE_URL", "DATABASE_URL_UNPOOLED", "NEON_PROJECT_ID"]}
    assert keys.get_value(name, "DATABASE_URL_UNPOOLED") == direct
    assert keys.get_value(name, "DATABASE_URL") == (
        f"postgresql://neondb_owner:{password}@ep-quiet-sun-a1b2c3d4-pooler.ap-southeast-2.aws.neon.tech"
        "/neondb?sslmode=require")
    assert keys.get_value(name, "NEON_PROJECT_ID") == PROJECT_ID
    unseen(result, password, account)


def test_neon_body_with_organisation_and_pooler_host(phoenix_env, real, upstream):
    name = project(phoenix_env, "neon")
    connect("neon", {"organisation": "org-bold-sky-123", "default_region": "aws-us-east-2"})
    password = secrets.token_hex(16)
    neon(upstream, password, pooler="pool.example.neon.tech")
    result = keymaker.make(name, ["neon"], who="tester")
    assert upstream.requests[0]["body"] == {"project": {"name": "demo", "region_id": "aws-us-east-2",
                                                        "org_id": "org-bold-sky-123"}}
    assert keys.get_value(name, "DATABASE_URL") == \
        f"postgresql://neondb_owner:{password}@pool.example.neon.tech/neondb?sslmode=require"
    unseen(result, password)


def test_neon_project_limit_words(phoenix_env, real, upstream):
    name = project(phoenix_env, "neon")
    connect("neon", {})
    upstream.answers[("POST", "/api/v2/projects")] = (422, {"code": "", "message": "projects limit exceeded"})
    result = keymaker.make(name, ["neon"], who="tester")
    assert result["problems"]["neon"] == "Neon refused: your plan has no room for another project."
    assert result["saved"] == {}


def test_neon_makes_no_second_database_when_a_connection_string_is_saved(phoenix_env, real, upstream):
    name = project(phoenix_env, "neon")
    connect("neon", {})
    mine = "postgresql://u:" + secrets.token_hex(8) + "@direct.example/db"
    keys.set_key(name, "DATABASE_URL_UNPOOLED", mine)
    neon(upstream, secrets.token_hex(16), pooler=None)
    result = keymaker.make(name, ["neon"], who="tester")
    assert upstream.requests == [] and result["saved"] == {}
    assert result["problems"]["neon"].startswith("Neon: DATABASE_URL_UNPOOLED is already saved")
    assert keys.get_value(name, "DATABASE_URL_UNPOOLED") == mine and keys.get_value(name, "DATABASE_URL") in (None, "")


def test_neon_proxy_unchanged_and_refuses_making():
    data = tomllib.loads((REPO / "services" / "neon" / "service.toml").read_text())
    assert [(r["method"], r["path"]) for r in data["proxy"]["allow"]] == [
        ("GET", "/api/v2/projects"), ("GET", "/api/v2/projects/*"), ("GET", "/api/v2/projects/*/branches")]
    svc = services.get("neon")
    rules = proxy.spec_from_service(svc).rules
    assert proxy.find_rule(rules, "POST", "/api/v2/projects") is None
    for path in (f"/api/v2/projects/{PROJECT_ID}/connection_uri",
                 f"/api/v2/projects/{PROJECT_ID}/branches/br-1/connection_uri"):
        assert proxy.find_rule(rules, "GET", path) is None
    make_rules = services.make_spec(svc).rules
    assert [(r.method, r.path) for r in make_rules] == [("POST", "/api/v2/projects")]
    assert proxy.find_rule(make_rules, "GET", f"/api/v2/projects/{PROJECT_ID}/connection_uri") is None


# ---------- OpenRouter ----------

def test_openrouter_uses_management_key(phoenix_env, real, upstream):
    name = project(phoenix_env, "openrouter")
    svc = services.get("openrouter")
    assert svc["account_keys"] == ["OPENROUTER_API_KEY"] and svc["make"]["key"] == "OPENROUTER_MANAGEMENT_KEY"
    normal, management = _value("normal"), _value("management")
    keys.write_secret_file(svc["secrets_file"], {"OPENROUTER_API_KEY": normal,
                                                 "_".join(["OPENROUTER", "MANAGEMENT", "KEY"]): management})
    made = _value("or")
    upstream.answers[("POST", "/keys")] = (201, {"data": {"name": "phoenix-demo"}, "key": made})
    row = {r["service"]: r for r in keymaker.status(name)}["openrouter"]
    assert row["state"] == "ready" and "key for making project keys" in row["words"]
    result = keymaker.make(name, who="tester")
    assert upstream.asked() == [("POST", "/keys", {"name": "phoenix-demo"})]
    assert [r["auth"] for r in upstream.requests] == [f"Bearer {management}"]
    assert result["saved"] == {"openrouter": ["OPENROUTER_API_KEY"]}
    assert keys.get_value(name, "OPENROUTER_API_KEY") == made
    assert result["notes"]["openrouter"] == \
        "Set a spending limit on key phoenix-demo at openrouter.ai if you want one."
    unseen(result, made, management, normal)


def test_openrouter_needs_management_key(phoenix_env, real, upstream):
    name = project(phoenix_env, "openrouter")
    svc = services.get("openrouter")
    keys.write_secret_file(svc["secrets_file"], {"OPENROUTER_API_KEY": _value("normal")})
    row = {r["service"]: r for r in keymaker.status(name)}["openrouter"]
    assert row["state"] == "needs-account-key"
    assert row["link"] == "https://openrouter.ai/settings/management-keys"
    assert "manage API keys (a management key)" in row["words"]
    result = keymaker.make(name, ["openrouter"], who="tester")
    assert result["problems"]["openrouter"] == row["words"] and upstream.requests == []


def test_openrouter_proxy_unchanged():
    data = tomllib.loads((REPO / "services" / "openrouter" / "service.toml").read_text())
    assert [(r["method"], r["path"]) for r in data["proxy"]["allow"]] == [("GET", "/key"), ("GET", "/models")]
    assert data["proxy"]["key"] == "OPENROUTER_API_KEY"
    assert proxy.find_rule(proxy.spec_from_service(services.get("openrouter")).rules, "POST", "/keys") is None


@pytest.mark.parametrize("name", ["cloudflare", "sentry", "resend", "neon", "openrouter"])
def test_providers_listed(name):
    assert keymaker._provider(name) is not None and services.get(name)["make"]
