"""The Acceptance step: runs the task's checks in fake check containers."""
import pytest

from helpers.stepunit import git, load, make_ctx, make_work, write
from phoenix9 import checklock, scrub

mod = load("acceptance")
FILES = ["tests/phoenix/task-1/test_1.py"]


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def ctx_for(tmp_path, adapters, work, done_when=(), things=None):
    ctx = make_ctx(tmp_path, adapters, work, "acceptance")
    ctx.task["done_when"] = list(done_when)
    ctx.things = things or {}
    return ctx


def cmd(c):
    return {"text": f"`{c}`", "command": c}


def test_acceptance_runs_locked_files_with_profile_command(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work, things={"checks": FILES})
    checklock.lock(ctx.run.folder, 1, work, FILES)
    res = mod.run(ctx)
    assert res.status == "pass"
    argv = " ".join(adapters.docker.argvs[0])
    assert FILES[0] in argv and ctx.project.profile["image"] in argv
    assert res.produces["exit-codes"][0]["exit_code"] == 0


def test_acceptance_fallback_runs_each_done_when_command(tmp_path, adapters, work):
    ctx = ctx_for(tmp_path, adapters, work, [cmd("python3 a.py"), cmd("python3 b.py")], {"checks": "spec-done-when"})
    res = mod.run(ctx)
    assert res.status == "pass" and len(adapters.docker.argvs) == 2
    assert [c["command"] for c in res.produces["exit-codes"]] == ["python3 a.py", "python3 b.py"]
    assert "python3 b.py" in " ".join(adapters.docker.argvs[1])


def test_acceptance_plain_bullets_shown_not_run(tmp_path, adapters, work):
    ctx = ctx_for(tmp_path, adapters, work, [cmd("python3 a.py"), {"text": "it is documented", "command": None}])
    mod.run(ctx)
    assert len(adapters.docker.argvs) == 1
    text = (ctx.run.folder / "tasks/1/attempt-1/checks.txt").read_text()
    assert "shown, not run: it is documented" in text


def test_acceptance_nonzero_fails_with_reason_per_command(tmp_path, adapters, work):
    adapters.docker.exit_codes += [1, 0, 2]
    adapters.docker.outputs += ["...\nFAILED tests/test_a.py::test_x - boom\n", "ok", "Traceback\nlast line"]
    ctx = ctx_for(tmp_path, adapters, work, [cmd("pytest a"), cmd("ok"), cmd("pytest c")])
    res = mod.run(ctx)
    assert res.status == "fail" and len(res.reasons) == 2
    assert res.reasons[0] == "Check `pytest a` failed (exit 1): FAILED tests/test_a.py::test_x - boom"
    assert "exit 2" in res.reasons[1] and "last line" in res.reasons[1]


def test_acceptance_nothing_to_run_fails(tmp_path, adapters, work):
    res = mod.run(ctx_for(tmp_path, adapters, work, [{"text": "plain", "command": None}]))
    assert res.status == "fail" and res.reasons == ["Task 1 has nothing Phoenix can run to check it"]
    assert adapters.docker.argvs == []


def test_acceptance_broken_lock_fails(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work, things={"checks": FILES})
    checklock.lock(ctx.run.folder, 1, work, FILES)
    (work / FILES[0]).write_text("changed\n")
    res = mod.run(ctx)
    assert res.status == "fail" and "was changed" in res.reasons[0] and adapters.docker.argvs == []


def test_checks_txt_is_scrubbed(tmp_path, adapters, work):
    scrub.add_secrets(["super-secret-value-123"])
    adapters.docker.outputs += ["token=super-secret-value-123\n"]
    ctx = ctx_for(tmp_path, adapters, work, [cmd("python3 a.py")])
    res = mod.run(ctx)
    text = (ctx.run.folder / "tasks/1/attempt-1/checks.txt").read_text()
    assert "[secret]" in text and "super-secret-value-123" not in text
    assert "super-secret-value-123" not in str(res.produces)


SH = ["tests/phoenix/r/task-1/1-a.sh", "tests/phoenix/r/task-1/2-b.sh"]


def test_each_sh_check_runs_on_its_own(tmp_path, adapters, work):
    """`sh a.sh b.sh` only runs a.sh: each shell check gets its own run, and the second failing counts."""
    write(work, {SH[0]: "exit 0\n", SH[1]: "exit 1\n"})
    ctx = make_ctx(tmp_path, adapters, work, "acceptance", profile="platform")
    ctx.things = {"checks": SH}
    checklock.lock(ctx.run.folder, 1, work, SH)
    adapters.docker.exit_codes += [0, 1]
    res = mod.run(ctx)
    assert len(adapters.docker.argvs) == 2
    assert [c["command"] for c in res.produces["exit-codes"]] == [f"sh {SH[0]}", f"sh {SH[1]}"]
    assert res.status == "fail" and len(res.reasons) == 1 and SH[1] in res.reasons[0]


def test_checklock_check_commands():
    assert checklock.check_commands({"check_command": "sh {files}"}, SH) == [f"sh {f}" for f in SH]
    assert checklock.check_commands({"check_command": "bash -e {files}"}, SH) == [f"bash -e {f}" for f in SH]
    assert checklock.check_commands({"check_command": "python3 -m pytest -q {files}"}, SH) == \
        ["python3 -m pytest -q " + " ".join(SH)]
    assert checklock.check_commands({"check_command": "sh {files}"}, ["a b.sh"]) == ["sh 'a b.sh'"]
