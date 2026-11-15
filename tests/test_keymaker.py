"""Key maker: only [make] rules reach the upstream, made values are saved unseen, status words, API and CLI guards."""
import dataclasses
import json
import secrets
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from phoenix9 import adapters as adapters_mod, keymaker, keys, paths, proxy, services
from phoenix9.__main__ import main
from phoenix9.ops import common, keys as ops_keys, services as ops_services
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)
from test_proxy import Upstream

REPO = Path(__file__).resolve().parent.parent

ACME = '''name = "acme"
title = "Acme"
support = "store-and-wire"
website = "https://acme.example/keys"
account_keys = ["ACME_ACCOUNT_KEY"]
hosts = ["acme.example"]

[[project_keys]]
name = "ACME_API_KEY"
secret = true
[[project_keys]]
name = "ACME_ORG"
secret = false
[[project_keys]]
name = "ACME_SITE"
secret = false
required = false

[[account_settings]]
name = "organisation"
label = "Organisation"
default = "acme-default"

[proxy]
upstream = "https://api.acme.example/v1"
auth_header = "Authorization"
auth_format = "Bearer {key}"
key = "ACME_ACCOUNT_KEY"
[[proxy.allow]]
method = "GET"
path = "/me"

[check]
method = "GET"
path = "/me"

[make]
needs = "make keys (Keys: Write)"
key_page = "https://acme.example/account-keys"
[[make.allow]]
method = "POST"
path = "/keys"
'''

# A service whose maker key is not an account key (like OpenRouter's management key).
BETA = '''name = "beta"
title = "Beta"
support = "store-and-wire"
account_keys = ["BETA_KEY"]
hosts = ["beta.example"]

[[project_keys]]
name = "BETA_TOKEN"

[proxy]
upstream = "https://api.beta.example"
auth_header = "Authorization"
auth_format = "Bearer {key}"
key = "BETA_KEY"
[[proxy.allow]]
method = "GET"
path = "/key"

[check]
method = "GET"
path = "/key"

[make]
key = "BETA_MAKER_KEY"
needs = "manage keys"
key_page = "https://beta.example/management"
[[make.allow]]
method = "POST"
path = "/keys"
'''


def _value(tag: str) -> str:
    """A made-up, high-entropy value built at run time."""
    return f"made-{tag}-{secrets.token_hex(12)}"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """The real services plus Acme and Beta, as the library."""
    root = tmp_path / "lib"
    shutil.copytree(REPO / "services", root / "services", ignore=shutil.ignore_patterns("__pycache__"))
    for name, text in (("acme", ACME), ("beta", BETA)):
        (root / "services" / name).mkdir()
        (root / "services" / name / "service.toml").write_text(text)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    return root


@pytest.fixture
def demo(phoenix_env, lib):
    """Project demo using Acme, Beta, Clerk and Stripe."""
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "phoenix.toml").write_text('services = ["acme", "beta", "clerk", "stripe"]\n')
    return folder


@pytest.fixture
def upstream():
    """A recording upstream that answers {"key": <value>}."""
    u = Upstream()
    u.made = _value("api")
    u.reply["body"] = json.dumps({"key": u.made}).encode()
    yield u
    u.close()


@pytest.fixture
def real(upstream, monkeypatch):
    """Adapters with the real proxy (pointed at the local upstream) and real http."""
    started = []

    class LocalProxy:
        def start(self, spec, key, *, log_path, step, bind="127.0.0.1", ports=None):
            started.append({"spec": spec, "key": key, "step": step})
            local = dataclasses.replace(spec, upstream=upstream.url)
            return proxy.serve(local, key, log_path=Path(log_path), step=step, bind=bind,
                               allow_plain_http_upstream=True)

    fake = SimpleNamespace(proxy=LocalProxy(), http=adapters_mod.Http(), started=started)
    monkeypatch.setattr(common, "make_adapters", lambda: fake)
    return fake


def connect(name: str, values: dict, settings: dict | None = None):
    """Save account keys and mark the service connected (no check)."""
    svc = services.get(name)
    keys.write_secret_file(svc["secrets_file"], values)
    reg = services.read_registry()
    reg[name] = {"connected": True, "settings": settings or {}}
    services.write_registry(reg)


class AcmeMaker:
    """Tries a [proxy]-only call (must be refused), then makes a key."""

    seen: list = []

    @staticmethod
    def make(call, ctx):
        AcmeMaker.seen.append(ctx)
        refused = call("GET", "/me")
        status, body = call("POST", "/keys", {"name": f"phoenix-{ctx['project']}"})
        if status != 200:
            raise keymaker.Refused("Acme refused.")
        return {"ACME_API_KEY": body["key"], "ACME_ORG": ctx["settings"]["organisation"],
                "note": f"Made key phoenix-{ctx['project']} (the [proxy] call got {refused[0]})"}


class BrokenMaker:
    """Always fails with an error carrying a value."""

    @staticmethod
    def make(call, ctx):
        raise RuntimeError("boom " + ctx["keys"].get("SECRETISH", "x"))


@pytest.fixture
def makers(monkeypatch):
    """Test providers for Acme and Beta."""
    AcmeMaker.seen = []
    monkeypatch.setitem(keymaker.PROVIDERS, "acme", AcmeMaker)
    monkeypatch.setitem(keymaker.PROVIDERS, "beta", BrokenMaker)


def everything_written() -> str:
    """Every file Phoenix wrote outside the key stores (logs, events, command records, registry)."""
    stores = {paths.secrets(), paths.keys()}
    return "".join(p.read_text(errors="replace") for p in paths.home().rglob("*")
                   if p.is_file() and not any(s in p.parents for s in stores))


def test_only_make_rules_reach_upstream_and_values_stay_unseen(demo, real, makers, upstream):
    account = _value("account")
    connect("acme", {"ACME_ACCOUNT_KEY": account}, {"organisation": "acme-org"})
    result = keymaker.make("demo", who="tester")
    assert result["saved"] == {"acme": ["ACME_API_KEY", "ACME_ORG"]}
    assert [(r["method"], r["path"]) for r in upstream.requests] == [("POST", "/keys")]
    assert json.loads(upstream.requests[0]["body"]) == {"name": "phoenix-demo"}
    assert upstream.requests[0]["headers"]["Authorization"] == f"Bearer {account}"
    assert "got 403" in result["notes"]["acme"]
    started = real.started[0]
    assert started["step"] == "keys-make" and [(r.method, r.path) for r in started["spec"].rules] == [("POST", "/keys")]
    assert keys.get_value("demo", "ACME_API_KEY") == upstream.made
    flags = {k["name"]: k["secret"] for k in keys.list_keys("demo")}
    assert flags["ACME_API_KEY"] is True and flags["ACME_ORG"] is False
    seen = json.dumps(result) + everything_written()
    assert upstream.made not in seen and account not in seen
    assert "keys.made" in seen and "project keys demo make" in seen


def test_ctx_has_settings_and_only_plain_key_values(demo, real, makers):
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    keys.set_key("demo", "ACME_SITE", "https://demo.example", secret=False)
    keys.set_key("demo", "OTHER_SECRET", _value("other"), secret=True)
    keymaker.make("demo", ["acme"], who="tester")
    ctx = AcmeMaker.seen[0]
    assert ctx["project"] == "demo" and ctx["settings"] == {"organisation": "acme-default"}
    assert ctx["keys"] == {"ACME_SITE": "https://demo.example"}


def test_existing_values_are_kept(demo, real, makers, upstream):
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    mine = _value("mine")
    keys.set_key("demo", "ACME_API_KEY", mine)
    keys.add_empty("demo", "ACME_ORG", secret=False)
    rows = {r["service"]: r for r in keymaker.status("demo")}
    assert rows["acme"]["missing"] == ["ACME_ORG"] and rows["acme"]["state"] == "ready"
    result = keymaker.make("demo", ["acme"], who="tester")
    assert result["saved"] == {"acme": ["ACME_ORG"]}
    assert keys.get_value("demo", "ACME_API_KEY") == mine
    assert upstream.made not in json.dumps(result) + everything_written()


def test_status_words(demo, makers):
    rows = {r["service"]: r for r in keymaker.status("demo")}
    acme = rows["acme"]
    assert acme["state"] == "needs-account-key" and acme["link"] == "https://acme.example/account-keys"
    assert acme["words"] == "Save a Acme account key that can make keys (Keys: Write) in Settings > Services > Acme."
    clerk = rows["clerk"]
    assert clerk["state"] == "manual" and clerk["link"] == "https://dashboard.clerk.com/last-active?path=api-keys"
    assert clerk["words"] == ("Paste PUBLIC_CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY from "
                              "https://dashboard.clerk.com/last-active?path=api-keys into Project > Settings > Keys.")
    assert rows["stripe"]["state"] == "manual" and "manual for now" in rows["stripe"]["words"]
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    acme = {r["service"]: r for r in keymaker.status("demo")}["acme"]
    assert acme["state"] == "ready" and acme["words"] == "Phoenix can make ACME_API_KEY and ACME_ORG with your saved Acme key."
    keys.set_key("demo", "ACME_API_KEY", _value("a"))
    keys.set_key("demo", "ACME_ORG", "org", secret=False)
    assert {r["service"]: r for r in keymaker.status("demo")}["acme"]["state"] == "done"


def test_maker_key_not_an_account_key_decides_ready(demo, makers):
    connect("beta", {"BETA_KEY": _value("beta")})
    assert {r["service"]: r for r in keymaker.status("demo")}["beta"]["state"] == "needs-account-key"
    connect("beta", {"BETA_KEY": _value("beta"), "BETA_MAKER_KEY": _value("maker")})
    assert {r["service"]: r for r in keymaker.status("demo")}["beta"]["state"] == "ready"


def test_one_failing_provider_does_not_stop_another(demo, real, makers, upstream):
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    connect("beta", {"BETA_KEY": _value("beta"), "BETA_MAKER_KEY": _value("maker")})
    hidden = _value("hidden")
    keys.set_key("demo", "SECRETISH", hidden, secret=False)
    result = keymaker.make("demo", ["beta", "acme"], who="tester")
    assert result["saved"] == {"acme": ["ACME_API_KEY", "ACME_ORG"]}
    assert result["problems"]["beta"] == "Beta: making the keys failed (RuntimeError)."
    assert "BETA_TOKEN" in result["still_missing"] and "ACME_API_KEY" not in result["still_missing"]
    assert hidden not in json.dumps(result)
    assert "Phoenix can't" not in json.dumps(result)


def test_not_ready_services_get_their_words_as_problems(demo, makers):
    result = keymaker.make("demo", ["acme", "clerk", "nope"], who="tester")
    assert result["saved"] == {}
    assert result["problems"]["acme"].startswith("Save a Acme account key")
    assert result["problems"]["clerk"].startswith("Paste ")
    assert result["problems"]["nope"] == "The project does not use a service called 'nope'."


def test_step_proxy_spec_has_no_make_rule(lib):
    for name, svc in services.load_library().items():
        if not svc["proxy"]:
            continue
        step_rules = set(proxy.spec_from_service(svc).rules)
        if svc["make"]:
            make_rules = set(services.make_spec(svc).rules)
            assert not (make_rules - set(proxy.parse_rules(svc["proxy"]["allow"]))) & step_rules, name
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    spec, _ = ops_services.proxy_spec_for("acme")
    assert [(r.method, r.path) for r in spec.rules] == [("GET", "/me")]
    assert proxy.find_rule(spec.rules, "POST", "/keys") is None


def test_make_block_is_checked(tmp_path, lib):
    acme = services.get("acme")
    assert acme["make"]["key"] == "ACME_ACCOUNT_KEY" and acme["make"]["needs"].startswith("make keys")
    bad = ACME.replace('path = "/keys"', 'path = "/keys/../x"').replace("key_page = \"https", "key_page = \"http")
    (lib / "services" / "acme" / "service.toml").write_text(bad)
    problems = " ".join(services.load_problems())
    assert "[make]" in problems and "key_page must be an https:// link" in problems
    assert services.get("acme") is None
    keys_only = (REPO / "services" / "clerk" / "service.toml").read_text() + '\n[make]\n[[make.allow]]\nmethod = "GET"\npath = "/x"\n'
    (lib / "services" / "clerk" / "service.toml").write_text(keys_only)
    assert any("a [make] block needs a store-and-wire service" in p for p in services.load_problems())


def test_connect_takes_the_optional_maker_key(demo, monkeypatch):
    rows = {r["name"]: r for r in ops_services.list_global()}
    assert rows["beta"]["make_key"] == {"name": "BETA_MAKER_KEY", "saved": False}
    assert rows["acme"]["make_key"] is None and rows["clerk"]["make_key"] is None
    ops_services.connect("beta", {"BETA_KEY": _value("beta")}, who="tester", check=False)
    assert {r["name"]: r for r in ops_services.list_global()}["beta"]["make_key"]["saved"] is False
    maker = _value("maker")
    out = ops_services.connect("beta", {"BETA_MAKER_KEY": maker}, who="tester", check=False)
    assert maker not in json.dumps(out)
    saved = keys.read_secret_file("service-beta.env")
    assert saved["BETA_MAKER_KEY"] == maker and saved["BETA_KEY"]
    row = {r["name"]: r for r in ops_services.list_global()}["beta"]
    assert row["make_key"] == {"name": "BETA_MAKER_KEY", "saved": True} and "BETA_MAKER_KEY" not in row["ends_in"]
    with pytest.raises(common.OpsError):
        ops_services.connect("acme", {"ACME_ACCOUNT_KEY": "x" * 20, "BETA_MAKER_KEY": maker}, who="t", check=False)


def test_ops_make_checks_the_services_list(demo):
    with pytest.raises(common.OpsError):
        ops_keys.make("demo", "acme", "tester")
    assert ops_keys.make_status("demo")[0]["service"] == "acme"


def test_api_needs_confirm(api, demo):
    status, body = api("/api/projects/demo/keys/make", "POST", POST_HEADERS, {"services": ["acme"]})
    assert status == 400 and body["message"] == "Making keys needs confirmation."
    status, body = api("/api/projects/demo/keys/make", "POST", POST_HEADERS, {"confirm": True})
    assert status == 200 and body["data"]["saved"] == {} and "ACME_API_KEY" in body["data"]["still_missing"]
    status, body = api("/api/projects/demo/keys/make")
    assert status == 200 and {r["service"] for r in body["data"]} == {"acme", "beta", "clerk", "stripe"}
    assert api("/api/projects/demo/keys/make", "POST", POST_HEADERS, {"confirm": True, "services": "acme"})[0] == 400


def test_cli_needs_yes(capsys, demo, real, makers, upstream):
    connect("acme", {"ACME_ACCOUNT_KEY": _value("account")})
    assert main(["project", "keys", "demo", "make"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert keys.get_value("demo", "ACME_API_KEY") in (None, "")
    assert main(["project", "keys", "demo", "make", "--service", "acme", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Saved ACME_API_KEY, ACME_ORG (acme)." in out and upstream.made not in out
    assert keys.get_value("demo", "ACME_API_KEY") == upstream.made
