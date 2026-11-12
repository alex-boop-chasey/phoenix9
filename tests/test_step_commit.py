"""The Commit step and git.passed_tasks (real temp git repo)."""
import pytest

from helpers.stepunit import git, load, make_ctx, make_work, write
from phoenix9 import failmodes
from phoenix9 import git as pgit

mod = load("commit")


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def test_commit_trailers_and_progress_line(tmp_path, adapters, work):
    write(work, {"a.py": "x = 1\n"})
    ctx = make_ctx(tmp_path, adapters, work, "commit")
    res = mod.run(ctx)
    sha = res.produces["commit"]
    assert res.status == "pass" and sha == git(work, "rev-parse", "HEAD").strip()
    msg = git(work, "log", "-1", "--format=%B%an <%ae>")
    assert msg.startswith("Task 1: Add a")
    for t in ("Phoenix-Run: r", "Phoenix-Task: 1", "Phoenix-Attempt: 1", "Phoenix 9 <phoenix@localhost>"):
        assert t in msg
    assert (ctx.run.folder / "progress.md").read_text() == f"Task 1 passed on attempt 1: {sha[:12]} Add a\n"


def test_commit_never_adds_env(tmp_path, adapters, work):
    write(work, {"a.py": "x = 1\n", ".env": "KEY=abc\n", "sub/.env.local": "K=1\n"})
    mod.run(make_ctx(tmp_path, adapters, work, "commit"))
    files = git(work, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["a.py"]
    assert (work / ".env").exists()


def test_commit_nothing_fails(tmp_path, adapters, work):
    res = mod.run(make_ctx(tmp_path, adapters, work, "commit"))
    assert res.status == "fail" and res.reasons == ["Nothing to commit"]
    write(work, {".env": "KEY=abc\n"})
    assert mod.run(make_ctx(tmp_path, adapters, work, "commit")).status == "fail"


def test_passed_tasks_from_trailers(tmp_path, work):
    base = git(work, "rev-parse", "HEAD").strip()
    for n in (3, 1):
        write(work, {f"f{n}.py": "x\n"})
        pgit.commit(work, f"Task {n}", {"Phoenix-Run": "r", "Phoenix-Task": str(n)})
    write(work, {"other.py": "x\n"})
    pgit.commit(work, "no trailer", {})
    assert pgit.passed_tasks(work, base) == [1, 3]
    with pytest.raises(pgit.GitError):
        pgit.passed_tasks(work, "nonsense")


def test_commit_already_done_records_no_new_commit(tmp_path, adapters, work):
    ctx = make_ctx(tmp_path, adapters, work, "commit")
    marker = failmodes.already_done_marker(ctx.run.folder, 1, ctx.attempt)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("x\n")
    head = git(work, "rev-parse", "HEAD").strip()
    res = mod.run(ctx)
    assert res.status == "pass" and res.produces["commit"] == head
    assert git(work, "rev-parse", "HEAD").strip() == head
    assert "already done: nothing needed changing" in (ctx.run.folder / "progress.md").read_text()
