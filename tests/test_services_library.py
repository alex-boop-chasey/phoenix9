"""The services library: the real services/ folder loads, and broken service folders are reported."""
import pytest

from phoenix9 import keys, proxy, services, settings

STORE = ["cloudflare", "github", "openrouter", "resend", "sentry", "supabase"]
KEYS_ONLY = ["clerk", "mux", "sanity", "stripe"]


def test_all_ten_services_load_without_errors():
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
    assert [r["path"] for r in sentry["proxy"]["allow"]] == ["/organizations/", "/organizations/*/projects/"]
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
