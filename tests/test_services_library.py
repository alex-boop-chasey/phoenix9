"""The services library: the real services/ folder loads, and broken service folders are reported."""
import pytest

from phoenix9 import keys, proxy, services, settings

STORE = ["cloudflare", "github", "neon", "openrouter", "resend", "sentry", "supabase"]
KEYS_ONLY = ["clerk", "mux", "sanity", "stripe"]


def test_all_eleven_services_load_without_errors():
    assert sorted(services.load_library()) == sorted(STORE + KEYS_ONLY)
    assert services.load_problems() == []


def test_store_and_wire_have_proxy_check_and_install_md():
    from phoenix9 import paths
    for name in STORE:
        svc = services.get(name)
        assert svc["support"] == "store-and-wire" and svc["proxy"] and svc["check"]
        assert svc["account_keys"] and svc["proxy"]["key"] in svc["account_keys"]
        assert (paths.library() / "services" / name / "install.md").is_file()


def test_keys_only_have_no_proxy():
    for name in KEYS_ONLY:
        svc = services.get(name)
        assert svc["support"] == "keys-only" and svc["proxy"] is None and svc["check"] is None
        assert svc["account_keys"] == []


def test_check_call_is_an_allowed_rule():
    for name in STORE:
        svc = services.get(name)
        spec = proxy.spec_from_service(svc)
        assert proxy.find_rule(spec.rules, svc["check"]["method"], svc["check"]["path"]), name


def test_sentry_hosts_empty():
    assert services.get("sentry")["hosts"] == []
    # Sentry's API answers 404 without the trailing slash, so its paths keep it (and the folder still loads).
    sentry = services.get("sentry")
    assert sentry["check"]["path"] == "/organizations/" and services.load_problems() == []
    assert [r["path"] for r in sentry["proxy"]["allow"]] == [
        "/organizations/", "/organizations/*/projects/", "/teams/*/*/projects/", "/projects/*/*/keys/"]
    cf = services.get("cloudflare")
    assert cf["check"]["fallback_path"] == "/accounts/{account_id}/tokens/verify"
    assert "/accounts/*/tokens/verify" in [r["path"] for r in cf["proxy"]["allow"]]
    assert services.get("github")["hosts"] == [] and services.get("github")["secrets_file"] == "github.env"
    assert services.get("supabase")["secrets_file"] == "service-supabase.env"


GOOD = '''name = "demo"
title = "Demo"
support = "store-and-wire"
account_keys = ["DEMO_TOKEN"]
hosts = ["demo.example.com"]
[proxy]
upstream = "https://api.demo.example.com"
auth_header = "Authorization"
auth_format = "Bearer {key}"
key = "DEMO_TOKEN"
[[proxy.allow]]
method = "GET"
path = "/things"
[check]
method = "GET"
path = "/things"
'''

BAD = {
    "bad support": (GOOD.replace('"store-and-wire"', '"sometimes"'), "support"),
    "proxy on keys-only": (GOOD.replace('"store-and-wire"', '"keys-only"'), "keys-only"),
    "key not in account_keys": (GOOD.replace('key = "DEMO_TOKEN"', 'key = "OTHER"'), "account_keys"),
    "bad rule": (GOOD.replace('path = "/things"\n[check]', 'path = "/things//x"\n[check]'), "empty part"),
    "host with scheme": (GOOD.replace('"demo.example.com"', '"https://demo.example.com"'), "bare domain"),
    "wildcard host": (GOOD.replace('"demo.example.com"', '"*.example.com"'), "bare domain"),
    "name differs from folder": (GOOD.replace('name = "demo"', 'name = "other"'), "folder name"),
    "fallback not allowed": (GOOD + 'fallback_path = "/nope"\n', "fallback"),
    "fallback unknown setting": (GOOD + 'fallback_path = "/things/{nothing}"\n', "not an account setting"),
    "tag too long": (GOOD.replace('support = "store-and-wire"', 'support = "store-and-wire"\ntag = "' + "x" * 31 + '"'),
                     "at most 30"),
    "tag not plain words": (GOOD.replace('support = "store-and-wire"', 'support = "store-and-wire"\ntag = "<b>Best</b>"'),
                            "plain words"),
    "check not allowed": (GOOD.replace('[check]\nmethod = "GET"\npath = "/things"', '[check]\nmethod = "GET"\npath = "/nope"'),
                          "allowed calls"),
}


def put(tmp_path, monkeypatch, text):
    (tmp_path / "services" / "demo").mkdir(parents=True)
    (tmp_path / "services" / "demo" / "service.toml").write_text(text)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(tmp_path))


def test_good_temp_service_loads(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, GOOD)
    assert services.load_problems() == [] and list(services.load_library()) == ["demo"]


@pytest.mark.parametrize("case", sorted(BAD))
def test_bad_service_folders_reported_not_crashing(tmp_path, monkeypatch, case):
    text, word = BAD[case]
    put(tmp_path, monkeypatch, text)
    assert services.load_library() == {}
    problems = services.load_problems()
    assert problems and any(word in p for p in problems)


def test_tag_is_optional_and_kept(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, GOOD.replace('support = "store-and-wire"', 'support = "store-and-wire"\ntag = "' + "x" * 30 + '"'))
    assert services.load_problems() == [] and services.get("demo")["tag"] == "x" * 30


def test_database_tags():
    assert services.get("neon")["tag"] == "Default database"
    assert services.get("supabase")["tag"] == "Other database"
    assert services.get("stripe")["tag"] == ""


def test_neon_keys_settings_and_hosts():
    neon = services.get("neon")
    rows = {k["name"]: k for k in neon["project_keys"]}
    assert rows["DATABASE_URL"]["secret"] and rows["DATABASE_URL"]["required"]
    assert rows["DATABASE_URL_UNPOOLED"]["secret"] and not rows["DATABASE_URL_UNPOOLED"]["required"]
    assert not rows["NEON_PROJECT_ID"]["secret"] and not rows["NEON_PROJECT_ID"]["public"]
    assert not rows["NEON_PROJECT_ID"]["required"]
    assert neon["account_keys"] == ["NEON_API_KEY"] and neon["hosts"] == ["neon.tech"]
    assert [s["name"] for s in neon["account_settings"]] == ["organisation", "default_region"]
    assert neon["website"] == "https://console.neon.tech/app/settings/api-keys"


def test_neon_proxy_allows_only_reads():
    neon = services.get("neon")
    assert neon["proxy"]["upstream"] == "https://console.neon.tech" and neon["proxy"]["key"] == "NEON_API_KEY"
    assert {r["method"] for r in neon["proxy"]["allow"]} == {"GET"}
    assert [r["path"] for r in neon["proxy"]["allow"]] == [
        "/api/v2/projects", "/api/v2/projects/*", "/api/v2/projects/*/branches", "/api/v2/projects/*/connection_uri"]
    spec = proxy.spec_from_service(neon)
    assert proxy.find_rule(spec.rules, "GET", "/api/v2/projects")
    assert proxy.find_rule(spec.rules, "GET", "/api/v2/projects/abc/connection_uri")
    assert proxy.find_rule(spec.rules, "DELETE", "/api/v2/projects/abc") is None
    assert proxy.find_rule(spec.rules, "POST", "/api/v2/projects") is None
    assert neon["check"]["method"] == "GET" and neon["check"]["path"] == "/api/v2/projects"


def test_project_new_prefills_from_loader(phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "phoenix.toml").write_text('preset = "quick"\n')
    from phoenix9 import project_services
    project_services.set_services("demo", ["supabase"], "alex")
    rows = {r["name"]: r for r in keys.list_keys("demo")}
    assert {n: rows[n]["secret"] for n in ("PUBLIC_SUPABASE_URL", "PUBLIC_SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")} == {
        "PUBLIC_SUPABASE_URL": False, "PUBLIC_SUPABASE_PUBLISHABLE_KEY": False, "SUPABASE_SECRET_KEY": True}
    assert "supabase.co" in settings.load_project(folder)["domains"]["allow"]


def test_every_service_key_has_help_and_public_keys_are_not_secret():
    from phoenix9 import paths
    for name, svc in services.load_library().items():
        for k in svc["project_keys"]:
            assert k["help"], f"{name} {k['name']} needs help text"
            assert not (k["public"] and k["secret"]), k["name"]
            assert k["public"] == k["name"].startswith("PUBLIC_"), k["name"]
        if svc["project_keys"]:
            assert (paths.library() / "services" / name / "install.md").is_file(), name


def test_key_fields_default_and_optional_flags():
    rows = {k["name"]: k for k in services.get("supabase")["project_keys"]}
    assert rows["PUBLIC_SUPABASE_URL"]["public"] and rows["PUBLIC_SUPABASE_URL"]["required"]
    assert not rows["DATABASE_URL"]["required"] and rows["DATABASE_URL"]["secret"]
    assert services.get("mux")["project_keys"][0]["secret"] is False


def test_public_and_secret_together_is_refused(tmp_path):
    from pathlib import Path
    folder = Path(tmp_path) / "x"
    folder.mkdir()
    data = {"name": "x", "title": "X", "project_keys": [{"name": "PUBLIC_X", "secret": True, "public": True}]}
    values, problems = services._parse(data, folder, "x")
    assert values is None and any("both public and secret" in p for p in problems)
