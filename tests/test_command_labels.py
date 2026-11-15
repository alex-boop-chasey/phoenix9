"""Real actions name what they were doing when they fail (one `command.failed` event) and keep the reason;
probes that fail on purpose record nothing."""
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from fakes import FakeHost, fake_adapters
from phoenix9 import chat, doctor, events, paths, project, runs, statusreport
from phoenix9.ops import common, github, service
from phoenix9.ops.common import OpsError
from test_step_merge import world  # noqa: F401  (world is a fixture)


def fake_token() -> str:
    """A GitHub-token-shaped fake, built from pieces so no key-shaped literal is in the code."""
    return "gh" + "p" + "_" + "Zx7" * 10


def failed_events() -> list[dict]:
    return [e for e in events.read(paths.events()) if e["type"] == "command.failed"]


def one_failure(what: str, rc: int) -> dict:
    """The single command.failed event; it names `what` and the exit code and hides the secret."""
    (event,) = failed_events()
    assert event["data"]["what"] == what and event["data"]["exit_code"] == rc
    assert fake_token() not in event["data"]["stderr_tail"] and "[secret]" in event["data"]["stderr_tail"]
    return event


def failing_host(rc: int = 1) -> FakeHost:
    """A fake host whose every command fails with a reason that carries a secret."""
    host = FakeHost()
    host.script([], rc, "", f"remote: access denied for {fake_token()}\n")
    return host


def assert_reason_in(text: str) -> None:
    assert "access denied" in text and fake_token() not in text


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def test_discard_branch_names_the_github_delete_and_keeps_why(tmp_path):
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    _git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("a\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "first")
    _git(code, "remote", "add", "origin", str(origin))
    _git(code, "branch", "phoenix/r1")
    _git(code, "push", "-q", "origin", "phoenix/r1")
    ad = fake_adapters(tmp_path)
    ad.host = failing_host()
    (note,) = runs.discard_branch(ad, "proj", "r1")
    one_failure("Deleting the build's branch on GitHub", 1)
    assert "phoenix/r1 was not deleted on GitHub" in note and "exit code 1" in note
    assert_reason_in(note)


def test_edit_finish_push_names_the_push_and_keeps_why(tmp_path, monkeypatch):
    from phoenix9 import editfinish, edits
    code = paths.projects() / "demo" / "code"
    code.mkdir(parents=True)
    _git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("a\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "first")
    (code.parent / "phoenix.toml").write_text('profile = "python-script"\n')
    ad = fake_adapters(tmp_path)
    monkeypatch.setattr(common, "make_adapters", lambda: ad)
    rec = edits.start("demo", "one")
    (open(os.path.join(rec["folder"], "a.txt"), "w")).write("changed\n")
    sha = editfinish.commit_edit(rec, "one", "cli")
    ad.host = failing_host(128)
    with pytest.raises(RuntimeError) as err:
        editfinish.publish(ad, rec, sha, [], "cli")
    one_failure("Pushing the quick edit's branch to GitHub", 128)
    assert "could not push the branch" in str(err.value)
    assert_reason_in(str(err.value))


def test_project_run_labels_the_command_with_its_what():
    with pytest.raises(OpsError) as err:
        project._run(failing_host(), "Could not create GitHub repo alex/demo", ["gh", "repo", "create", "alex/demo"])
    event = one_failure("Could not create GitHub repo alex/demo", 1)
    assert event["data"]["program"] == "gh repo"
    assert_reason_in(str(err.value))


def _listed(name: str) -> None:
    (paths.projects() / name).mkdir(parents=True)
    (paths.projects() / name / "CLAUDE.md").write_text("x")


def test_chat_start_names_the_start_and_keeps_why():
    _listed("alpha")
    host = failing_host()
    host.script(["systemctl", "is-enabled"], 1, "disabled\n")       # a probe: fails on purpose, records nothing
    from phoenix9.projectchat import NotReady
    with pytest.raises(NotReady) as err:
        chat.start_unit(host, "alpha")
    one_failure("Starting the project's chat", 1)
    assert_reason_in(str(err.value))


def test_chat_disable_failure_is_returned_in_plain_words():
    _listed("alpha")
    host = FakeHost()
    host.script(["systemctl", "is-enabled"], 0, "enabled\n")
    host.script(["systemctl", "disable"], 1, "", f"remote: access denied for {fake_token()}\n")
    note = chat.start_unit(host, "alpha")
    one_failure(chat.DISABLE_WHAT, 1)
    assert note.startswith(chat.DISABLE_WHAT + " failed (exit code 1)")
    assert_reason_in(note)


def test_chat_stop_failure_is_returned_in_plain_words():
    _listed("alpha")
    note = chat.stop_unit(failing_host(), "alpha")
    one_failure("Stopping the project's chat", 1)
    assert_reason_in(note)
    assert chat.stop_unit(FakeHost(), "alpha") is None


def test_service_restart_names_the_restart_and_keeps_why(tmp_path):
    ad = fake_adapters(tmp_path)
    ad.host = failing_host()
    done, err = service.restart_unit(ad, "agent")
    one_failure("Restarting the agent service", 1)
    assert not done
    assert_reason_in(err)


def test_github_repo_list_names_the_lookup_and_keeps_why(tmp_path, monkeypatch):
    ad = fake_adapters(tmp_path)
    ad.host = failing_host()
    ad.host.script(["gh", "auth", "status"], 0)
    ad.host.script(["gh", "api", "user"], 0, "alex\n")
    ad.host.script(["gh", "api", "user/orgs"], 0, "")
    monkeypatch.setattr(common, "make_adapters", lambda: ad)
    found = github.repos()
    one_failure(github.REPOS_WHAT, 1)
    assert found["repos"] == [] and len(found["problems"]) == 1
    assert_reason_in(found["problems"][0])


def test_statusreport_merge_requests_names_the_lookup_and_keeps_why(tmp_path, monkeypatch):
    ad = fake_adapters(tmp_path)
    ad.host = failing_host()
    monkeypatch.setattr(github, "_repo_projects", lambda project: [("demo", "alex/demo")])
    (line,) = statusreport.merge_requests(ad, time.time())
    one_failure(statusreport.PRS_WHAT, 1)
    assert line.startswith("- demo: GitHub did not list its open merge requests")
    assert_reason_in(line)


def test_merge_step_push_names_the_push_and_keeps_why(world):  # noqa: F811
    ctx, _code, _origin = world
    fake = ctx.adapters.host.fake
    fake.script(["git"], 128, "", f"remote: access denied for {fake_token()}\n")
    ctx.adapters.host.run = lambda argv, timeout=60, what=None: fake.run(argv, timeout, what=what)
    from helpers.stepunit import load
    result = load("merge").run(ctx)
    one_failure("Pushing the build's branch to GitHub", 128)
    assert result.status == "fail" and "access denied" in " ".join(result.reasons)     # the runner scrubs reasons


def test_probes_record_nothing(tmp_path):
    _listed("alpha")
    host = failing_host(3)
    assert chat.unit_state(host, "alpha") == "inactive"
    ad = fake_adapters(tmp_path)
    ad.host = failing_host(3)
    ok, _detail, _fix = doctor.check_services(SimpleNamespace(ad=ad))
    assert not ok
    assert failed_events() == []
