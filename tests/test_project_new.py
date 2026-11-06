"""phoenix project new: every source, the eight creation steps, undo, and the CLI."""
import json
import subprocess
import sys

import pytest

from phoenix9 import git, keys, paths, project, settings
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


@pytest.fixture
def env(phoenix_env, tmp_path, monkeypatch):
    """Fake adapters injected into ops, and a temp .claude.json path."""
    from fakes import fake_adapters
    fakes = fake_adapters(tmp_path)
    claude = tmp_path / "claude.json"
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude))
    fakes.host.files[str(claude)] = json.dumps({"projects": {}})
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    return {"fakes": fakes, "host": fakes.host, "claude": str(claude), "projects": phoenix_env["projects"]}


def opts(**kw):
    return {"name": "demo", "description": "A demo thing.", "no_new_repo": True, **kw}


def create(env, **kw):
    return project.create(opts(**kw), env["fakes"], "alex")


def calls(env, *prefix):
    return [c for c in env["host"].calls if c[:len(prefix)] == list(prefix)]


def test_new_empty_no_repo(env):
    result = create(env, profile="python-script")
    folder = env["projects"] / "demo"
    assert result["path"] == str(folder) and result["steps"][0] == "Checking the form"
    for sub in ("research", "specs", "plans", "sessions"):
        assert (folder / "notes" / sub).is_dir()
    assert (folder / "notes").stat().st_mode & 0o777 == 0o700
    text = (folder / "CLAUDE.md").read_text()
    assert text.startswith("# demo\n\nA demo thing.") and "- Profile: python-script" in text
    assert "@notes/NOW.md" in text and "fill this in" not in text.lower()
    assert "from an empty folder; next: first chat refines CLAUDE.md" in (folder / "notes/NOW.md").read_text()
    assert "created from an empty folder, profile python-script" in (folder / "notes/decisions.md").read_text()
    assert "· alex · created by alex" in (folder / "notes/changelog.md").read_text()
    data = settings.load_project(folder)
    assert data == {"profile": "python-script"}
    assert (folder / "phoenix.toml").read_text().count("preset") == 0
    info = json.loads((folder / ".phoenix/project.json").read_text())
    assert info["who"] == "alex" and info["source"] == "empty" and info["chat_session_url"] is None
    assert info["services_set_up"] == [] and info["repo"] is None
    assert git.git(folder / "code", "rev-list", "--count", "HEAD").strip() == "1"
    assert not calls(env, "systemctl", "enable") and not calls(env, "systemctl", "start")
    trusted = json.loads(env["host"].files[env["claude"]])["projects"]
    assert trusted[str(folder)]["hasTrustDialogAccepted"] is True
    assert not (folder / ".vscode").exists()
    assert "| demo |" in (env["projects"] / "INDEX.md").read_text()
    types = [json.loads(x)["type"] for x in paths.events().read_text().splitlines()]
    assert "project.created" in types and "command" in types


def test_new_without_profile_writes_no_phoenix_toml(env):
    create(env)
    folder = env["projects"] / "demo"
    assert not (folder / "phoenix.toml").exists()
    assert json.loads((folder / ".phoenix/project.json").read_text())["profile"] == ""
    assert "created from an empty folder\n" in (folder / "notes/decisions.md").read_text()


def test_new_from_python_cli_template_runs_offline(env):
    create(env, name="demo-app", template="python-cli", no_new_repo=True)
    code = env["projects"] / "demo-app" / "code"
    assert "Hello" in (code / "src/demo_app/__init__.py").read_text()
    assert "A demo thing." in (code / "pyproject.toml").read_text()
    assert "{{" not in (code / "pyproject.toml").read_text()
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=code, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert settings.load_project(code.parent)["profile"] == "python-script"


def test_new_from_recipe_template_calls_host_with_pinned_command(env):
    create(env, template="astro-tailwind")
    host = env["host"]
    i = next(i for i, c in enumerate(host.calls) if c[:3] == ["pnpm", "create", "astro@5.1.1"])
    assert host.cwds[i] == str(env["projects"] / "demo" / "code")
    assert settings.load_project(env["projects"] / "demo")["profile"] == "web"


def test_new_with_repo_clones_via_gh(env):
    result = create(env, repo="alex/thing", profile="web")
    assert calls(env, "gh", "repo", "view", "alex/thing")
    clone = calls(env, "gh", "repo", "clone", "alex/thing")[0]
    assert clone[4] == str(env["projects"] / "demo" / "code")
    assert result["repo"] == "alex/thing"
    assert "- Repo: alex/thing" in (env["projects"] / "demo/CLAUDE.md").read_text()


def test_new_with_code_path_records_it(env, tmp_path):
    existing = tmp_path / "old-code"
    existing.mkdir()
    create(env, code=str(existing), profile="web")
    folder = env["projects"] / "demo"
    assert f"- Code: {existing}" in (folder / "CLAUDE.md").read_text()
    assert json.loads((folder / ".phoenix/project.json").read_text())["code"] == str(existing)
    assert not (folder / "code").exists()


def test_new_repo_creates_and_pushes_via_gh(env):
    result = create(env, profile="python-script", no_new_repo=False, new_repo="alex")
    assert calls(env, "gh", "repo", "create", "alex/demo", "--private")
    folder = env["projects"] / "demo"
    assert git.git(folder / "code", "remote", "get-url", "origin").strip() == "https://github.com/alex/demo.git"
    assert any(c[0] == "git" and c[-4:] == ["push", "-u", "origin", "main"] for c in env["host"].calls)
    assert result["repo"] == "alex/demo"
    assert json.loads((folder / ".phoenix/project.json").read_text())["repo"] == "alex/demo"
    assert "- Repo: alex/demo" in (folder / "CLAUDE.md").read_text()


def test_new_repo_gets_dependabot_for_detected_ecosystems(env):
    create(env, name="a", template="python-cli", no_new_repo=False, new_repo="alex")
    text = (env["projects"] / "a/code/.github/dependabot.yml").read_text()
    assert text.startswith("version: 2\nupdates:\n")
    assert 'package-ecosystem: "pip"' in text and 'interval: "weekly"' in text
    assert "open-pull-requests-limit: 5" in text and 'directory: "/"' in text
    assert ".github/dependabot.yml" in git.git(env["projects"] / "a/code", "ls-files")


def test_dependabot_falls_back_to_profile(env):
    create(env, name="d", profile="desktop", no_new_repo=False, new_repo="alex")
    text = (env["projects"] / "d/code/.github/dependabot.yml").read_text()
    assert 'package-ecosystem: "npm"' in text and 'package-ecosystem: "cargo"' in text


def test_no_dependabot_when_nothing_detected_or_no_new_repo(env):
    create(env, name="n", no_new_repo=False, new_repo="alex")
    assert not (env["projects"] / "n/code/.github").exists()
    create(env, name="m", profile="web")
    assert not (env["projects"] / "m/code/.github").exists()


def test_github_template_with_and_without_new_repo(env):
    create(env, name="a", profile="web", template="alex/starter", no_new_repo=False, new_repo="alex")
    assert calls(env, "gh", "repo", "create", "alex/a", "--private", "--template", "alex/starter")
    create(env, name="b", profile="web", template="alex/starter")
    assert len(calls(env, "gh", "repo", "clone", "alex/starter")) == 1
    assert git.git(env["projects"] / "b/code", "rev-list", "--count", "HEAD").strip() == "1"


def test_services_and_keys_file(env, tmp_path):
    secret = "sk-test-SECRET-value-98765"
    kf = tmp_path / "keys.toml"
    kf.write_text(f'[[key]]\nname = "RESEND_API_KEY"\nvalue = "{secret}"\nsecret = true\n\n'
                  '[[key]]\nname = "PUBLIC_SUPABASE_URL"\nvalue = "https://x.supabase.co"\nsecret = false\n')
    create(env, profile="python-script", services=["resend", "supabase"], keys_file=str(kf))
    folder = env["projects"] / "demo"
    rows = {r["name"]: r for r in keys.list_keys("demo")}
    assert rows["RESEND_API_KEY"]["secret"] and rows["PUBLIC_SUPABASE_URL"]["value_if_not_secret"] == "https://x.supabase.co"
    assert "PUBLIC_SUPABASE_PUBLISHABLE_KEY" in rows
    allow = settings.load_project(folder)["domains"]["allow"]
    assert "api.resend.com" in allow and "supabase.co" in allow
    example = (folder / "code/.env.example").read_text()
    assert "RESEND_API_KEY=\n" in example and secret not in example
    for f in folder.rglob("*"):
        if f.is_file() and ".git/" not in str(f):
            assert secret not in f.read_text(errors="ignore"), f
    assert secret not in paths.events().read_text()


def test_bad_name_and_existing_folder_refused_before_anything_made(env):
    (env["projects"] / "taken").mkdir()
    for bad in ({"name": "Bad_Name"}, {"name": "taken"}, {"profile": "nope"}, {"services": ["nope"]},
                {"code": "/no/such/folder"}, {"template": "nope-tpl"}, {"repo": "a/b", "template": "python-cli"},
                {"no_new_repo": False}, {"keys_file": "/no/such.toml"}):
        before = sorted(env["projects"].iterdir())
        with pytest.raises(OpsError):
            create(env, **{"profile": "python-script", **bad})
        assert sorted(env["projects"].iterdir()) == before
    assert env["host"].calls == [] or not calls(env, "systemctl")
    env["host"].script(["gh", "repo", "view"], 1, "", "Could not resolve to a Repository")
    with pytest.raises(OpsError, match="Cannot see a/b on GitHub: Could not resolve"):
        create(env, repo="a/b", profile="web")


def test_failure_after_folder_undoes_everything(env, tmp_path):
    kf = tmp_path / "k.toml"
    kf.write_text('[[key]]\nname = "A_KEY"\nvalue = "v-12345678"\n')
    (env["projects"] / "INDEX.md").write_text("| other | - | (new) |\n")
    env["host"].files[env["claude"]] = "not json"
    with pytest.raises(OpsError, match="is not valid JSON; cannot mark"):
        create(env, profile="python-script", keys_file=str(kf))
    assert not (env["projects"] / "demo").exists()
    assert not (paths.keys() / "demo.toml").exists()
    assert (env["projects"] / "INDEX.md").read_text() == "| other | - | (new) |\n"


def test_failure_after_repo_created_says_repo_left(env):
    env["host"].files[env["claude"]] = "not json"
    with pytest.raises(OpsError) as err:
        create(env, profile="python-script", no_new_repo=False, new_repo="alex")
    assert "GitHub repo alex/demo was created and left in place; delete it by hand if you don't want it" in str(err.value)
    assert not (env["projects"] / "demo").exists()
    assert not calls(env, "gh", "repo", "delete")


def test_cli_new_json_and_progress_lines(env, capsys):
    assert main(["project", "new", "demo", "--profile", "python-script", "--template", "python-cli", "--no-new-repo"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "- Checking the form" and not any("chat on" in x for x in out)
    assert out[-1].startswith("Created ") and out[-1].endswith("/demo")
    assert main(["project", "new", "demo2", "--profile", "python-script", "--no-new-repo", "--services", "github", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "demo2" and data["services"] == ["github"] and "Writing CLAUDE.md" in data["steps"]
    assert main(["project", "templates", "--json"]) == 0
    assert "python-cli" in [t["name"] for t in json.loads(capsys.readouterr().out)]
    assert main(["project", "templates"]) == 0 and "Python CLI" in capsys.readouterr().out
    assert main(["settings", "explain", "demo"]) == 0
    assert "python-script" in capsys.readouterr().out


def test_cli_needs_new_repo_choice(env, capsys):
    assert main(["project", "new", "demo", "--profile", "python-script"]) == 1
    assert "--new-repo OWNER or --no-new-repo" in capsys.readouterr().err
    assert not (env["projects"] / "demo").exists()
