"""Remove a project from Phoenix and import it back: nothing is deleted, no service is touched."""
import json

import pytest

from phoenix9 import paths, project, project_removal, settings
from phoenix9.__main__ import main
from phoenix9.ops import common, projects
from phoenix9.ops.common import OpsError
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)
from test_project_cmds import env, make, run_cmd  # noqa: F401  (fixtures)


def tree(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def calls(host, *prefix):
    return [c for c in host.calls if c[:len(prefix)] == list(prefix)]


def trusted(env, folder):
    data = json.loads(next(v for k, v in env["host"].files.items() if k.endswith("claude.json")))
    return str(folder) in data["projects"]


def test_remove_keeps_files_and_hides_from_list(env):
    folder = make(env, "alpha")
    (folder / "code").mkdir()
    (folder / "code" / "main.py").write_text("print(1)")
    project.trust(env["host"], folder)
    assert trusted(env, folder)
    before = tree(folder)
    r = projects.remove("alpha", "tester")
    after = tree(folder)
    assert all(after[k] == v for k, v in before.items() if k != "notes/changelog.md")
    assert "removed from Phoenix" in after["notes/changelog.md"].decode()
    assert r["name"] == "alpha" and r["removed_on"]
    assert not calls(env["host"], "systemctl")          # Phoenix no longer runs per-project chat services
    assert not trusted(env, folder)
    assert [x["name"] for x in projects.list_()] == []
    assert settings.read_global()["removed_projects"][0]["name"] == "alpha"
    assert (paths.logs() / "commands.jsonl").read_text().count("project remove alpha") == 1


def test_remove_refuses_phoenix9_and_home(env):
    make(env, "phoenix9")
    make(env, "home")
    for name in ("phoenix9", "home"):
        with pytest.raises(OpsError, match="cannot be removed"):
            projects.remove(name, "tester")
        assert [x for x in projects.list_(include_agent=True) if x["name"] == name]
    assert not calls(env["host"], "systemctl", "disable")


def test_remove_unknown_and_twice(env):
    with pytest.raises(common.NotFound):
        projects.remove("nope", "tester")
    make(env, "alpha")
    projects.remove("alpha", "tester")
    with pytest.raises(common.Conflict):
        projects.remove("alpha", "tester")


def test_candidates_list_removed_and_unlisted(env):
    make(env, "alpha")
    make(env, "listed")
    (env["projects"] / "loose").mkdir()
    (env["projects"] / ".proj").mkdir()
    projects.remove("alpha", "tester")
    found = {c["name"]: c for c in projects.import_candidates()}
    assert set(found) == {"alpha", "loose"}
    assert found["alpha"]["removed_on"] and found["alpha"]["kind"] == "removed"
    assert found["loose"]["removed_on"] is None and found["loose"]["repo"] is None


def test_import_removed_project_restores_it(env):
    folder = make(env, "alpha")
    projects.remove("alpha", "tester")
    env["host"].calls.clear()
    r = projects.import_("alpha", "tester")
    assert r["was_removed"] and r["chat"] == "not set up yet"
    assert [x["name"] for x in projects.list_()] == ["alpha"]
    assert "removed_projects" not in settings.read_global()
    assert not calls(env["host"], "systemctl", "start")
    assert not (folder / ".vscode" / "tasks.json").exists()
    assert trusted(env, folder)
    assert "imported into Phoenix" in (folder / "notes" / "changelog.md").read_text()


def test_import_unlisted_folder_by_path_adds_files_without_overwriting(env):
    folder = env["projects"] / "loose"
    (folder / "notes").mkdir(parents=True)
    (folder / "notes" / "NOW.md").write_text("mine")
    r = projects.import_(str(folder), "tester")
    assert not r["was_removed"] and "CLAUDE.md" in r["added"] and "notes/NOW.md" not in r["added"]
    assert (folder / "notes" / "NOW.md").read_text() == "mine"
    assert (folder / "CLAUDE.md").is_file()
    assert [x["name"] for x in projects.list_()] == ["loose"]
    assert not calls(env["host"], "systemctl", "start")
    assert ".vscode/tasks.json" not in r["added"]


def test_import_never_overwrites_existing_claude_md(env):
    folder = make(env, "alpha", text="# alpha\n\nmy words\n")
    projects.remove("alpha", "tester")
    projects.import_("alpha", "tester")
    assert (folder / "CLAUDE.md").read_text() == "# alpha\n\nmy words\n"


def test_import_refuses_listed_missing_and_outside(env, tmp_path):
    make(env, "alpha")
    with pytest.raises(common.Conflict):
        projects.import_("alpha", "tester")
    with pytest.raises(common.NotFound):
        projects.import_("ghost", "tester")
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(OpsError, match="not inside"):
        projects.import_(str(tmp_path / "elsewhere"), "tester")


def test_create_starts_only_the_chat_unit(env):
    projects.new({"name": "fresh", "description": "x", "source": {"kind": "empty"}, "profile": "python-script",
                  "template": None, "services": [], "new_repo": None, "no_new_repo": True}, "tester")
    assert all("claude-rc-chat@fresh" in c[-1] for c in calls(env["host"], "systemctl"))
    assert trusted(env, env["projects"] / "fresh")


def test_cli_remove_needs_yes_and_import(env, capsys):
    folder = make(env, "alpha")
    code, _, err = run_cmd(capsys, "project", "remove", "alpha")
    assert code != 0 and "--yes" in (err + "")
    assert [x["name"] for x in projects.list_()] == ["alpha"]
    code, out, _ = run_cmd(capsys, "project", "remove", "alpha", "--yes")
    assert code == 0 and "Removed alpha" in out and folder.is_dir()
    code, out, _ = run_cmd(capsys, "project", "import", "--list", "--json")
    assert code == 0 and json.loads(out)[0]["name"] == "alpha"
    code, out, _ = run_cmd(capsys, "project", "import", "alpha")
    assert code == 0 and "Imported alpha" in out


def test_api_routes(api):
    make_project("alpha")
    status, body = api("/api/projects/alpha/remove", "POST", POST_HEADERS, {})
    assert status == 400
    status, body = api("/api/projects/alpha/remove", "POST", POST_HEADERS, {"confirm": True})
    assert status == 200 and body["data"]["name"] == "alpha"
    status, body = api("/api/projects")
    assert body["data"] == []
    status, body = api("/api/import/candidates")
    assert [c["name"] for c in body["data"]] == ["alpha"]
    status, body = api("/api/import", "POST", POST_HEADERS, {"target": "alpha"})
    assert status == 200 and body["data"]["was_removed"] is True
    status, body = api("/api/import", "POST", POST_HEADERS, {"target": "alpha"})
    assert status == 409
    status, body = api("/api/projects/home/remove", "POST", POST_HEADERS, {"confirm": True})
    assert status in (400, 404)


def test_api_has_no_chat_route_or_chat_fields(api):
    from phoenix9 import addresses
    make_project("alpha")
    addresses.save({"vscode_url": "https://code.example.test/"})
    assert api("/api/projects/alpha/chat/start", "POST", POST_HEADERS, {})[0] == 404
    status, body = api("/api/projects/alpha")
    assert status == 200 and body["data"]["vscode"]["reason"] is None
    for gone in ("chat", "chat_url", "chats", "state"):
        assert gone not in body["data"]


def test_list_folders_lists_visible_subfolders_only(env):
    root = paths.projects()
    (root / "alpha" / "sub").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "file.txt").write_text("x")
    top = projects.list_folders("")
    assert top["parent"] is None and [f["name"] for f in top["folders"]] == ["alpha"]
    inner = projects.list_folders(str(root / "alpha"))
    assert inner["parent"] == str(root.resolve()) or inner["parent"] == str(root)
    assert [f["name"] for f in inner["folders"]] == ["sub"]


def test_list_folders_refuses_outside_and_dotdot(env, tmp_path):
    (paths.projects() / "alpha").mkdir(parents=True)
    for bad in (str(tmp_path), "/", "/etc", str(paths.projects() / "alpha" / ".." / ".."), "../.."):
        with pytest.raises(OpsError):
            projects.list_folders(bad)
    with pytest.raises(OpsError):
        projects.list_folders(str(paths.projects() / "missing"))


def test_list_folders_skips_symlinks_that_leave_the_root(env, tmp_path):
    root = paths.projects()
    (root / "real").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    (root / "inside").symlink_to(root / "real")
    names = [f["name"] for f in projects.list_folders("")["folders"]]
    assert names == ["inside", "real"]
    with pytest.raises(OpsError):
        projects.list_folders(str(root / "escape"))


def test_api_folders(api):
    (paths.projects() / "alpha").mkdir(parents=True)
    status, body = api("/api/folders")
    assert status == 200 and [f["name"] for f in body["data"]["folders"]] == ["alpha"]
    status, body = api("/api/folders?path=/etc")
    assert status == 400


def test_check_files_adds_only_what_is_missing(env, capsys):
    folder = make(env, "alpha", text="# alpha\n\nmy words\n")
    (folder / "notes" / "NOW.md").write_text("mine")
    code, out, _ = run_cmd(capsys, "project", "check-files", "alpha")
    assert code == 0 and "alpha: added" in out and "notes/decisions.md" in out and "notes/NOW.md" not in out
    assert (folder / "CLAUDE.md").read_text() == "# alpha\n\nmy words\n"
    assert (folder / "notes" / "NOW.md").read_text() == "mine"
    assert all((folder / "notes" / s).is_dir() for s in project.NOTES_SUBFOLDERS)
    assert not (folder / "phoenix.toml").exists()
    code, out, _ = run_cmd(capsys, "project", "check-files", "alpha")
    assert code == 0 and "alpha: nothing missing" in out


def test_check_files_all_skips_folders_without_claude_md_and_removed(env, capsys):
    make(env, "alpha")
    make(env, "beta")
    (env["projects"] / "loose").mkdir()
    projects.remove("beta", "tester")
    code, out, _ = run_cmd(capsys, "project", "check-files", "--all")
    assert code == 0 and "alpha: added" in out and "beta" not in out and "loose" not in out
    assert not (env["projects"] / "loose" / "CLAUDE.md").exists()


def test_check_files_needs_a_name_or_all_and_a_real_project(env, capsys):
    code, _, err = run_cmd(capsys, "project", "check-files")
    assert code == 1 and "--all" in err
    with pytest.raises(common.NotFound):
        projects.check_files("ghost", "tester")


def chat_import(env, tmp_path, monkeypatch, mode):
    """Import an unlisted folder with a host whose chat unit comes up (or fails)."""
    from fakes.chathost import chat_adapters
    from phoenix9 import chatlink
    monkeypatch.setattr(chatlink, "send_to", lambda found, text, *a, **k: {"sent": True})
    chatlink.forget()
    folder = env["projects"] / "loose"
    (folder / "notes").mkdir(parents=True)
    fakes = chat_adapters(tmp_path, mode, folder, tmp_path / "claude.json")
    return folder, fakes


def test_import_chat_asleep_after_import(env, tmp_path, monkeypatch):
    folder, fakes = chat_import(env, tmp_path, monkeypatch, "ok")
    r = project_removal.import_("loose", "tester", fakes)
    assert r["chat"] == "sleeping" and "chat_message" not in r
    assert (folder / ".phoenix" / "chat.md").is_file()
    assert fakes.host.stopped == [10]


def test_import_chat_not_set_up_still_imports(env, tmp_path, monkeypatch, capsys):
    folder, fakes = chat_import(env, tmp_path, monkeypatch, "fail")
    r = project_removal.import_("loose", "tester", fakes)
    assert (folder / "CLAUDE.md").is_file()
    assert r["chat"] == "not set up yet"
    assert "chat not set up yet: press Chat to try again" in r["chat_message"]


def test_import_cli_shows_chat_words(env, tmp_path, monkeypatch, capsys):
    folder, fakes = chat_import(env, tmp_path, monkeypatch, "fail")
    monkeypatch.setattr(common, "make_adapters", lambda: fakes)
    code, out, _ = run_cmd(capsys, "project", "import", "loose")
    assert code == 0 and "chat not set up yet: press Chat to try again" in out


def test_import_forgets_phoenix_made_repo(env):
    folder = make(env, "alpha", meta={"repo": "me/alpha", "source": "empty", "phoenix_made_repo": "me/alpha",
                                      "phoenix_made_repo_id": "R_1"})
    projects.remove("alpha", "tester")
    project_removal.import_("alpha", "tester", env["fakes"])
    meta = json.loads((folder / ".phoenix" / "project.json").read_text())
    assert meta["repo"] == "me/alpha" and "phoenix_made_repo" not in meta and "phoenix_made_repo_id" not in meta
