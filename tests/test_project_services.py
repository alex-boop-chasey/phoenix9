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


def test_library_loads_nine_services():
    assert sorted(services.load_library()) == ["clerk", "github", "mux", "openrouter", "resend", "sanity", "sentry", "stripe", "supabase"]
    rows = [(k["name"], k["secret"], k["required"]) for k in services.get("resend")["project_keys"]]
    assert rows == [("RESEND_API_KEY", True, True), ("RESEND_FROM", False, True),
                    ("RESEND_WEBHOOK_SECRET", True, False)]
    assert services.get("nope") is None


def test_set_services_writes_toml_rows_domains_decision(demo):
    project_services.set_services("demo", ["supabase", "resend"], "alex")
    data = settings.load_project(demo)
    assert data["services"] == ["supabase", "resend"] and data["preset"] == "quick"
    assert data["domains"]["allow"] == ["supabase.co", "api.resend.com"]
    names = {r["name"]: r for r in keys.list_keys("demo")}
    assert set(names) == {"PUBLIC_SUPABASE_URL", "PUBLIC_SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "DATABASE_URL",
                         "SUPABASE_PROJECT_REF", "RESEND_WEBHOOK_SECRET", "RESEND_API_KEY",
                         "RESEND_FROM"}
    assert names["PUBLIC_SUPABASE_URL"]["secret"] is False and names["RESEND_API_KEY"]["has_value"] is False
    assert "uses Supabase and Resend (chosen by alex)" in (demo / "notes" / "decisions.md").read_text()
    assert "services set to supabase, resend" in (demo / "notes" / "changelog.md").read_text()


def test_unknown_service_refused(demo):
    with pytest.raises(OpsError, match="Unknown service: nope"):
        project_services.set_services("demo", ["resend", "nope"], "alex")
    assert "services" not in settings.load_project(demo)


def test_removing_service_keeps_shared_hosts(demo):
    project_services.set_services("demo", ["supabase", "resend", "openrouter"], "alex")
    # a hand-added host and a shared one must survive; only unneeded service hosts go
    data = settings.load_project(demo)
    data["domains"]["allow"].append("example.com")
    settings.save_project(demo, data)
    project_services.set_services("demo", ["supabase"], "alex")
    allow = settings.load_project(demo)["domains"]["allow"]
    assert allow == ["supabase.co", "example.com"]
    assert "RESEND_API_KEY" in {r["name"] for r in keys.list_keys("demo")}     # key rows are kept


def test_existing_key_values_kept(demo):
    keys.set_key("demo", "RESEND_API_KEY", "re_abcdefgh12345", True)
    project_services.set_services("demo", ["resend"], "alex")
    assert keys.container_env("demo") == {"RESEND_API_KEY": "re_abcdefgh12345"}
