"""Remove a project from Phoenix and import it back: nothing is deleted, the chat is set up again."""
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
    assert calls(env["host"], "systemctl", "disable", "-q", "--now", "claude-rc@alpha.service")
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
        assert [x for x in projects.list_() if x["name"] == name]
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
    assert r["was_removed"] and r["chat"] == "on"
    assert [x["name"] for x in projects.list_()] == ["alpha"]
    assert "removed_projects" not in settings.read_global()
    assert calls(env["host"], "systemctl", "enable", "-q", "claude-rc@alpha.service")
    assert calls(env["host"], "systemctl", "start", "claude-rc@alpha.service")
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
    assert calls(env["host"], "systemctl", "start", "claude-rc@loose.service")


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


def test_create_sets_up_and_starts_chat(env):
    from test_project_cmds import off_until_started
    off_until_started(env["host"])
    projects.new({"name": "fresh", "description": "x", "source": {"kind": "empty"}, "profile": "python-script",
                  "template": None, "services": [], "new_repo": None, "no_new_repo": True}, "tester")
    assert calls(env["host"], "systemctl", "enable", "-q", "claude-rc@fresh.service")
    assert calls(env["host"], "systemctl", "start", "claude-rc@fresh.service")
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


def test_api_chat_start_and_row_chat_shape(api):
    make_project("alpha")
    status, body = api("/api/projects/alpha/chat/start", "POST", POST_HEADERS, {})
    assert status == 200 and body["data"]["chat"]["state"] == "on" and body["data"]["chat"]["url"] is None
    status, body = api("/api/projects/alpha")
    assert body["data"]["chat"]["state"] == "on" and body["data"]["vscode"]["reason"] is None
    assert api("/api/projects/ghost/chat/start", "POST", POST_HEADERS, {})[0] == 404


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
