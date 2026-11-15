"""Tests for phoenix9/proc.py: the one helper that starts outside programs and records the ones that fail."""
import sys

import pytest

from phoenix9 import events, paths, proc
from phoenix9 import git as gitmod
from phoenix9.git import GitError

PY = sys.executable


def fake_token() -> str:
    """A GitHub-token-shaped fake, built from pieces so no key-shaped literal is in the code."""
    return "gh" + "p" + "_" + "Ab3" * 10


def failed_events() -> list[dict]:
    return [e for e in events.read(paths.events()) if e["type"] == "command.failed"]


def fail_with(err: str, rc: int = 3) -> list[str]:
    """A command that writes `err` to stderr and exits with `rc`."""
    return [PY, "-c", f"import sys; sys.stderr.write({err!r}); sys.exit({rc})"]


def test_result_unpacks_and_reads_like_a_finished_process():
    r = proc.run([PY, "-c", "print('hi')"])
    rc, out, err = r
    assert (rc, out, err) == (0, "hi\n", "")
    assert (r.rc, r.out, r.err) == (r.returncode, r.stdout, r.stderr) == (0, "hi\n", "")
    assert r == (0, "hi\n", "") and not r.failed


def test_timeout_gives_124_and_missing_program_127():
    rc, out, err = proc.run([PY, "-c", "import time; time.sleep(30)"], timeout=0.3)
    assert (rc, out, err) == (124, "", "timed out after 0.3s")
    rc, out, err = proc.run(["phoenix-no-such-program-here", "x"])
    assert (rc, out, err) == (127, "", "not found: phoenix-no-such-program-here")
    assert failed_events() == []


def test_bytes_mode_and_input():
    r = proc.run([PY, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"], input=b"abc", text=False)
    assert r == (0, b"ABC", b"")


def test_a_failing_action_records_one_scrubbed_event_with_the_step():
    secret = fake_token()
    with proc.context(project="alpha", run="r1", task=2, step="merge"):
        assert proc.current() == {"project": "alpha", "run": "r1", "task": 2, "step": "merge"}
        rc, _, _ = proc.run(fail_with(f"line one\nauth failed for {secret}\n"), what="Pushing the branch")
    assert rc == 3 and proc.current()["step"] is None
    (event,) = failed_events()
    assert (event["project"], event["run"], event["task"], event["step"]) == ("alpha", "r1", 2, "merge")
    assert event["data"]["what"] == "Pushing the branch" and event["data"]["exit_code"] == 3
    assert secret not in event["data"]["stderr_tail"] and "[secret]" in event["data"]["stderr_tail"]
    assert "line one" in event["data"]["stderr_tail"]
    assert secret not in paths.events().read_text()
    assert [e["type"] for e in events.read(paths.runs("alpha") / "r1" / "events.jsonl")] == ["command.failed"]


def test_timeout_and_not_found_with_what_are_recorded():
    proc.run([PY, "-c", "import time; time.sleep(30)"], what="Waiting", timeout=0.3)
    proc.run(["phoenix-no-such-program-here"], what="Looking")
    assert [(e["data"]["what"], e["data"]["exit_code"]) for e in failed_events()] == [("Waiting", 124), ("Looking", 127)]


def test_a_failing_probe_without_what_records_nothing():
    assert proc.run(fail_with("nope\n"))[0] == 3
    assert proc.run([PY, "-c", "pass"], what="Fine")[0] == 0
    assert failed_events() == []


def test_program_never_holds_arguments():
    assert proc.program(["/usr/bin/git", "-c", "x=y", "push", "origin", "secret-branch"]) == "git push"
    assert proc.program(["systemctl", "--user", "restart", "phoenix-api"]) == "systemctl restart"
    assert proc.program(["git", "-C", "/srv/x", "remote", "get-url"]) == "git remote"
    assert proc.program(["python3", "-c", "print('code')"]) == "python3"
    assert proc.program(["chown", "-R", "1:1", "/srv/projects/a"]) == "chown"
    assert proc.program(["gh"]) == "gh" and proc.program([]) == ""
    with proc.context(step="update"):
        proc.run(fail_with("x") + ["--flag=1", "/srv/my-private-place"], what="Thing")
    (event,) = failed_events()
    assert event["data"]["program"] == PY.rsplit("/", 1)[-1]
    assert "my-private-place" not in str(event) and "sys.exit" not in str(event) and event["step"] == "update"


def test_context_nests_and_keeps_outer_values():
    with proc.context(project="alpha", step="update"):
        with proc.context(step="merge"):
            assert proc.current()["project"] == "alpha" and proc.current()["step"] == "merge"
        assert proc.current()["step"] == "update"
    assert proc.current() == {"project": None, "run": None, "task": None, "step": None}


def test_tail_and_failure_text_are_scrubbed_and_capped():
    secret = fake_token()
    text = "\n".join(f"line {i}" for i in range(100)) + f"\nfinal {secret}\n\n"
    out = proc.tail(text)
    assert len(out.splitlines()) == 20 and out.endswith("final [secret]") and secret not in out
    assert len(proc.tail("x" * 5000)) == 2000
    line = proc.failure_text("Pushing the branch", (1, "", text))
    assert line == "Pushing the branch failed (exit code 1): final [secret]"
    assert proc.failure_text("Restarting", (2, "", "")) == "Restarting failed (exit code 2)"
    assert len(proc.failure_text("X", (1, "", "y" * 5000))) < 400


def test_an_event_that_cannot_be_written_never_breaks_the_caller(monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(events, "emit", broken)
    assert proc.run(fail_with("x"), what="Thing")[0] == 3


def test_git_error_text_is_scrubbed_and_capped_and_recorded(tmp_path):
    secret = fake_token()
    with pytest.raises(GitError) as e:
        gitmod.run_git(tmp_path, "rev-parse", f"--verify-{secret}" + "x" * 3000)
    text = str(e.value)
    assert secret not in text and "[secret]" in text
    (event,) = failed_events()
    assert event["data"]["what"] == "git rev-parse" and event["data"]["program"] == "git rev-parse"
    assert secret not in str(event)
    assert gitmod.run_git(tmp_path, "rev-parse", "--verify", "nope", check=False).returncode != 0
    assert len(failed_events()) == 1                  # check=False is a probe: nothing more recorded


def test_git_error_tail_hides_a_secret_in_stderr(monkeypatch, tmp_path):
    secret = fake_token()
    noisy = "\n".join(f"hint {i}" for i in range(200)) + f"\nfatal: bad token {secret}\n"
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda argv, **kw: proc.subprocess.CompletedProcess(argv, 128, b"", noisy.encode()))
    with pytest.raises(GitError) as e:
        gitmod.run_git(tmp_path, "push", "origin", "main")
    text = str(e.value)
    assert secret not in text and text.endswith("fatal: bad token [secret]")
    assert "hint 0\n" not in text and len(text) < 2600
    (event,) = failed_events()
    assert (event["data"]["program"], event["data"]["exit_code"]) == ("git push", 128)
    assert "origin" not in event["data"]["program"]
