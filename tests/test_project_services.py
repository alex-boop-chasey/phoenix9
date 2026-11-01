"""Choosing a project's services: phoenix.toml, empty key rows, hosts, decisions."""
import pytest

from phoenix9 import keys, project_services, services, settings
from phoenix9.ops.common import OpsError


@pytest.fixture
def demo(phoenix_env):
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes").mkdir(parents=True)
    (folder / "phoenix.toml").write_text('preset = "quick"\n')
    return folder


def test_library_loads_five_services():
    assert sorted(services.load_library()) == ["github", "openrouter", "resend", "sentry", "supabase"]
    assert services.get("resend")["project_keys"] == [{"name": "RESEND_API_KEY", "secret": True}]
    assert services.get("nope") is None


def test_set_services_writes_toml_rows_domains_decision(demo):
    project_services.set_services("demo", ["supabase", "resend"], "alex")
    data = settings.load_project(demo)
    assert data["services"] == ["supabase", "resend"] and data["preset"] == "quick"
    assert data["domains"]["allow"] == ["*.supabase.co", "api.resend.com"]
    names = {r["name"]: r for r in keys.list_keys("demo")}
    assert set(names) == {"SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "RESEND_API_KEY"}
    assert names["SUPABASE_URL"]["secret"] is False and names["RESEND_API_KEY"]["has_value"] is False
    assert "uses Supabase and Resend (chosen by alex)" in (demo / "notes" / "decisions.md").read_text()
    assert "services set to supabase, resend" in (demo / "notes" / "changelog.md").read_text()


def test_unknown_service_refused(demo):
    with pytest.raises(OpsError, match="Unknown service: nope"):
        project_services.set_services("demo", ["resend", "nope"], "alex")
    assert "services" not in settings.load_project(demo)


def test_removing_service_keeps_shared_hosts(demo):
    project_services.set_services("demo", ["github", "sentry", "openrouter"], "alex")
    # a hand-added host and a shared one must survive; only unneeded service hosts go
    data = settings.load_project(demo)
    data["domains"]["allow"].append("example.com")
    settings.save_project(demo, data)
    project_services.set_services("demo", ["github"], "alex")
    allow = settings.load_project(demo)["domains"]["allow"]
    assert allow == ["github.com", "api.github.com", "example.com"]
    assert "SENTRY_DSN" in {r["name"] for r in keys.list_keys("demo")}     # key rows are kept


def test_existing_key_values_kept(demo):
    keys.set_key("demo", "RESEND_API_KEY", "re_abcdefgh12345", True)
    project_services.set_services("demo", ["resend"], "alex")
    assert keys.container_env("demo") == {"RESEND_API_KEY": "re_abcdefgh12345"}
