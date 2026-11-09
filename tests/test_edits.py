"""Tests for quick edits: start, refusals, list, heartbeat, abandon, events (real git in temp repos)."""
import json
import os
import subprocess
import time

import pytest

from phoenix9 import atomic, edits, events, paths, state
from phoenix9.__main__ import main


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def proj(phoenix_env):
    """A project with a one-commit code/ repo on main."""
    code = phoenix_env["projects"] / "demo" / "code"
    code.mkdir(parents=True)
    _git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("a\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "first")
    return code


def _branches(code):
    return subprocess.run(["git", "branch", "--list", "edit/*"], cwd=code, capture_output=True, text=True).stdout


def test_start_makes_worktree_and_record(proj, capsys):
    assert main(["edit", "start", "demo", "--title", "Fix the typo"]) == 0
    folder = capsys.readouterr().out.strip()
    rec = json.loads(next((paths.home() / "edits").glob("*.json")).read_text())
    assert folder == rec["folder"] == str(paths.home() / "edits" / rec["id"])
    assert (os.path.exists(os.path.join(folder, "a.txt")))
    assert rec["branch"] == "edit/" + rec["id"] and rec["id"].endswith("-fix-the-typo")
    assert rec["status"] == "open" and rec["project"] == "demo" and rec["who"] == "cli"
    assert rec["branch"] in _branches(proj)
    assert any(e["type"] == "edit.started" for e in events.read(paths.events()))


def test_refuses_second_open_edit_and_running_build(proj):
    edits.start("demo", "one")
    with pytest.raises(edits.EditError, match="open quick edit"):
        edits.start("demo", "two")


def test_refuses_while_build_runs(proj):
    run = paths.runs("demo") / "20260101-000000-x"
    run.mkdir(parents=True)
    atomic.write_json(run / "state.json", state.new_state(run.name, "demo"))
    state.set_status(run, "running")
    with pytest.raises(edits.EditError, match="build is running"):
        edits.start("demo", "one")
    state.set_status(run, "done")
    edits.start("demo", "one")


def test_list_heartbeat_and_file_activity(proj, capsys):
    rec = edits.start("demo", "one")
    old = "2020-01-01T00:00:00+00:00"
    atomic.write_json(edits.record_file(rec["id"]), dict(rec, last_activity=old))
    assert edits.list_edits("demo")[0]["last_activity"] > old       # worktree files are newer
    assert main(["edit", "heartbeat", rec["id"]]) == 0
    assert json.loads(edits.record_file(rec["id"]).read_text())["last_activity"] > old
    time.sleep(1.1)
    (open(os.path.join(rec["folder"], "b.txt"), "w")).write("b")
    assert edits.list_edits("demo")[0]["last_activity"] >= edits.load(rec["id"])["last_activity"]
    capsys.readouterr()
    assert main(["edit", "list", "--project", "demo", "--json"]) == 0
    assert [e["id"] for e in json.loads(capsys.readouterr().out)["edits"]] == [rec["id"]]
    assert main(["edit", "list", "--project", "other", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["edits"] == []
    assert main(["edit", "heartbeat", "nope"]) == 1


def test_abandon_needs_yes_and_removes_everything(proj):
    rec = edits.start("demo", "one")
    assert main(["edit", "abandon", rec["id"]]) == 1
    assert os.path.isdir(rec["folder"])
    assert main(["edit", "abandon", rec["id"], "--yes"]) == 0
    assert not os.path.exists(rec["folder"]) and rec["branch"] not in _branches(proj)
    assert edits.load(rec["id"])["status"] == "abandoned"
    assert "edit.abandoned" in [e["type"] for e in events.read(paths.events())]
    edits.start("demo", "again")       # the project is free again


def _ready(proj, monkeypatch, tmp_path):
    """Give the project a profile, a fake adapter set and a bare 'origin'; return the adapters."""
    from fakes import fake_adapters
    from phoenix9.ops import common
    (proj.parent / "phoenix.toml").write_text('profile = "python-script"\n')
    ad = fake_adapters(tmp_path)
    monkeypatch.setattr(common, "make_adapters", lambda: ad)
    return ad


def test_finish_pushes_and_opens_merge_request(proj, monkeypatch, tmp_path, capsys):
    ad = _ready(proj, monkeypatch, tmp_path)
    ad.host.script(["gh", "pr", "create"], 0, "https://github.com/o/r/pull/9\n")
    rec = edits.start("demo", "Fix the typo")
    (open(os.path.join(rec["folder"], "a.txt"), "w")).write("fixed\n")
    assert main(["edit", "finish", rec["id"], "--message", "Fix typo"]) == 0
    done = edits.load(rec["id"])
    assert done["status"] == "finished" and done["pr"] == "https://github.com/o/r/pull/9"
    assert not os.path.exists(rec["folder"])
    argvs = [c for c in ad.host.calls if c[0] in ("git", "gh")]
    assert any("push" in c for c in argvs) and any(c[:3] == ["gh", "pr", "create"] for c in argvs)
    assert any("Made by cli; Alex merges this." in a for c in argvs for a in c)
    pr = next(c for c in argvs if c[:3] == ["gh", "pr", "create"])
    assert pr[pr.index("--label") + 1] == "needs Alex"
    assert any(c[:3] == ["gh", "label", "create"] and "needs Alex" in c for c in argvs)
    push = next(c for c in argvs if "push" in c)
    assert push[-1] == f"{done['commit']}:refs/heads/{rec['branch']}"
    body = subprocess.run(["git", "log", "-1", "--format=%B", done["commit"]], cwd=proj, capture_output=True, text=True)
    assert "Phoenix-Fix-By: cli" in body.stdout and f"Phoenix-Edit: {rec['id']}" in body.stdout
    parent = subprocess.run(["git", "rev-parse", done["commit"] + "^"], cwd=proj, capture_output=True, text=True)
    first = subprocess.run(["git", "rev-parse", "main"], cwd=proj, capture_output=True, text=True)
    assert parent.stdout == first.stdout                    # one squashed commit on top of the base
    docker_cmds = [a for a in ad.docker.argvs[0] if "pytest" in a or "python" in a]
    assert docker_cmds
    log = subprocess.run(["git", "log", "-1", "--format=%s", rec["branch"]], cwd=proj, capture_output=True, text=True)
    assert log.stdout.strip() == "Fix typo"
    assert "edit.finished" in [e["type"] for e in events.read(paths.events())]
    edits.start("demo", "next")        # a finished edit no longer blocks


def test_finish_failures_keep_the_edit_open(proj, monkeypatch, tmp_path):
    ad = _ready(proj, monkeypatch, tmp_path)
    rec = edits.start("demo", "one")
    with pytest.raises(edits.EditError, match="no changes"):
        edits.finish(rec["id"])
    (open(os.path.join(rec["folder"], ".env"), "w")).write("A=1\n")
    (open(os.path.join(rec["folder"], "pyproject.toml"), "w")).write('[project]\nname="x"\ndependencies=["y"]\n')
    ad.docker.exit_codes.append(1)
    with pytest.raises(edits.EditError) as err:
        edits.finish(rec["id"], adapters=ad)
    text = " ".join(err.value.problems)
    assert ".env" in text and "lockfile" in text and "tests failed" in text
    assert edits.load(rec["id"])["status"] == "open" and os.path.isdir(rec["folder"])
    assert not [c for c in ad.host.calls if c[:1] == ["git"] or c[:1] == ["gh"]]


def test_stalled_after_thirty_minutes(proj):
    rec = edits.start("demo", "one")
    atomic.write_json(edits.record_file(rec["id"]), dict(rec, last_activity="2020-01-01T00:00:00+00:00"))
    os.utime(rec["folder"] + "/a.txt", (1577836800, 1577836800))
    old = time.time() + 31 * 60
    assert edits.mark_stalled(old) == [rec["id"]]
    assert edits.load(rec["id"])["status"] == "stalled" and os.path.isdir(rec["folder"])
    edits.heartbeat(rec["id"])
    assert edits.load(rec["id"])["status"] == "open"


def test_unknown_project(proj):
    assert main(["edit", "start", "nope", "--title", "x"]) == 1


def test_unknown_project_and_agent_folder(proj, phoenix_env):
    (phoenix_env["projects"] / "home" / "code").mkdir(parents=True)
    with pytest.raises(edits.EditError, match="agent's folder"):
        edits.start("home", "x")


def test_stalled_edit_still_blocks_a_second(proj):
    rec = edits.start("demo", "one")
    atomic.write_json(edits.record_file(rec["id"]), dict(rec, status="stalled"))
    with pytest.raises(edits.EditError, match="open quick edit"):
        edits.start("demo", "two")


def test_chat_abandons_only_its_own(proj):
    rec = edits.start("demo", "one")
    with pytest.raises(edits.EditError, match="only Alex or that chat"):
        edits.abandon(rec["id"], "chat:home")
    assert edits.abandon(rec["id"], "cli")["status"] == "abandoned"
    mine = edits.start("demo", "two", who="chat:home")
    assert edits.abandon(mine["id"], "chat:home")["status"] == "abandoned"


def test_chat_may_not_change_safety_files(proj, monkeypatch, tmp_path):
    ad = _ready(proj, monkeypatch, tmp_path)
    (proj.parent / "phoenix.toml").write_text('profile = "python-script"\nsafety_files = ["guard/*.py"]\n')
    rec = edits.start("demo", "touch guard", who="chat:home")
    os.makedirs(os.path.join(rec["folder"], "guard"))
    (open(os.path.join(rec["folder"], "guard", "x.py"), "w")).write("x = 1\n")
    with pytest.raises(edits.EditError) as err:
        edits.finish(rec["id"], adapters=ad, who="chat:home")
    assert any("guard/x.py is a safety file" in p for p in err.value.problems)
    ad.host.script(["gh", "pr", "create"], 0, "https://github.com/o/r/pull/3\n")
    assert edits.finish(rec["id"], adapters=ad, who="cli")["status"] == "finished"      # Alex may


def test_checks_run_on_the_commit_and_a_later_change_is_refused(proj, monkeypatch, tmp_path):
    from phoenix9 import editfinish
    ad = _ready(proj, monkeypatch, tmp_path)
    rec = edits.start("demo", "one")
    (open(os.path.join(rec["folder"], "a.txt"), "w")).write("checked\n")
    sha = editfinish.commit_edit(rec, "one", "cli")
    seen = {}
    real = editfinish._run_tests

    def spy(adapters, rec_, ctx, checkout):
        seen["text"] = open(os.path.join(checkout, "a.txt")).read()
        (open(os.path.join(rec["folder"], "a.txt"), "w")).write("sneaked in after the checks\n")
        return real(adapters, rec_, ctx, checkout)
    monkeypatch.setattr(editfinish, "_run_tests", spy)
    problems, changes = editfinish.check(ad, rec, sha, "cli")
    assert problems == [] and seen["text"] == "checked\n"
    with pytest.raises(RuntimeError, match="not checked"):
        editfinish.publish(ad, rec, sha, changes, "cli")
    (open(os.path.join(rec["folder"], "a.txt"), "w")).write("checked\n")
    _git(rec["folder"], "commit", "-q", "--allow-empty", "-m", "moved")
    with pytest.raises(RuntimeError, match="changed after the checks"):
        editfinish.publish(ad, rec, sha, changes, "cli")
    assert not [c for c in ad.host.calls if "push" in c]


def test_label_failure_still_opens_the_merge_request(proj, monkeypatch, tmp_path):
    ad = _ready(proj, monkeypatch, tmp_path)
    ad.host.script(["gh", "label", "create"], 1, "", "HTTP 403")
    ad.host.script(["gh", "pr", "create"], 0, "https://github.com/o/r/pull/4\n")
    rec = edits.start("demo", "one")
    (open(os.path.join(rec["folder"], "a.txt"), "w")).write("x\n")
    assert edits.finish(rec["id"], adapters=ad)["pr"].endswith("/4")
    pr = next(c for c in ad.host.calls if c[:3] == ["gh", "pr", "create"])
    assert "--label" not in pr


def test_agent_folder_from_settings_is_protected(proj, phoenix_env):
    from phoenix9 import paths as p_
    from phoenix9.project_removal import PROTECTED
    p_.config().mkdir(parents=True, exist_ok=True)
    (p_.config() / "global.toml").write_text('[agent]\nfolder = "/srv/projects/hq"\n')
    assert "hq" in PROTECTED and "home" in PROTECTED and "phoenix9" in PROTECTED and "demo" not in PROTECTED
    assert "agent's folder" in PROTECTED["hq"]
    (phoenix_env["projects"] / "hq" / "code").mkdir(parents=True)
    with pytest.raises(edits.EditError, match="agent's folder"):
        edits.start("hq", "x")
