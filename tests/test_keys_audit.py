"""The keys audit: names and modes only, never a value."""
import json

from phoenix9 import keys, paths, settings
from phoenix9.__main__ import main
from phoenix9.ops import keys as keys_ops

SENTINEL = "sk-SENTINEL-123"


def make_project(name, services=()):
    folder = paths.projects() / name
    (folder / "notes").mkdir(parents=True)
    (folder / "code").mkdir()
    settings.save_project(folder, {"services": list(services)})
    return folder


def test_audit_lists_names_not_values(capsys, phoenix_env):
    keys.write_secret_file("service-supabase.env", {"SUPABASE_ACCESS_TOKEN": SENTINEL})
    keys.write_secret_file("claude.env", {"CLAUDE_CODE_OAUTH_TOKEN": SENTINEL})
    make_project("alpha")
    keys.set_key("alpha", "MY_KEY", SENTINEL)
    assert main(["keys", "audit"]) == 0
    plain = capsys.readouterr()
    assert main(["keys", "audit", "--json"]) == 0
    js = capsys.readouterr()
    assert SENTINEL not in plain.out + plain.err + js.out + js.err
    data = json.loads(js.out)
    assert {r["file"] for r in data["global"]} == {"service-supabase.env", "claude.env"}
    assert "SUPABASE_ACCESS_TOKEN" in plain.out and "MY_KEY" in plain.out and "No problems found." in plain.out


def test_audit_flags_wrong_mode(phoenix_env):
    keys.write_secret_file("github.env", {"GH_TOKEN": SENTINEL})
    (paths.secrets() / "github.env").chmod(0o640)
    problems = keys_ops.audit()["problems"]
    assert any("github.env" in p and "640" in p for p in problems)
    assert SENTINEL not in json.dumps(keys_ops.audit())


def test_audit_flags_missing_expected_service_key(phoenix_env):
    make_project("alpha", ["resend"])
    keys.add_empty("alpha", "RESEND_API_KEY")
    problems = keys_ops.audit()["problems"]
    assert any("alpha" in p and "RESEND_API_KEY" in p for p in problems)
    keys.write_secret_file("service-nothere.env", {"X_KEY": SENTINEL})
    assert any("nothere" in p and "not in the services library" in p for p in keys_ops.audit()["problems"])


def test_audit_marks_public_keys_in_env_example(phoenix_env):
    make_project("alpha")
    keys.set_key("alpha", "PUBLIC_URL", "https://x.example", secret=False)
    keys.set_key("alpha", "SECRET_ONE", SENTINEL)
    rows = {r["name"]: r for r in keys_ops.audit()["projects"]}
    assert ".env.example" in rows["PUBLIC_URL"]["used"] and rows["PUBLIC_URL"]["secret"] is False
    assert ".env.example" not in rows["SECRET_ONE"]["used"] and rows["SECRET_ONE"]["set"] is True
