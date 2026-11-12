"""Verify's affected scope: the checks plus the touched tests, and a whole-suite checkpoint every few tasks."""
import json
from pathlib import Path

import pytest

from helpers.stepunit import git, load, make_ctx, make_work, write
from phoenix9 import checklock, state
from test_step_verify import FILES, script_reports
from test_step_builder import project  # noqa: F401

mod = load("verify")
PASS = ("pytest.xml", "pytest-pass.xml")
FAIL = ("pytest.xml", "pytest-mixed.xml")


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def make(tmp_path, adapters, work, every=5, edit=None):
    """A verify context in the affected scope; the check file is committed, then `edit` files are left uncommitted."""
    write(work, {FILES[0]: "x\n", "src/a.py": "a = 1\n", "tests/test_a.py": "import a\n"})
    ctx = make_ctx(tmp_path, adapters, work, "verify")
    ctx.step.settings.update(scope="affected", suite_every=every)
    ctx.things = {"checks": FILES}
    checklock.lock(ctx.run.folder, 1, work, FILES)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    state.set_task(ctx.run.folder, 1, attempt_base=git(work, "rev-parse", "HEAD").strip())
    write(work, edit if edit is not None else {"src/a.py": "a = 2\n"})
    return ctx


def argvs(adapters):
    """Each docker command as one string."""
    return [" ".join(a) for a in adapters.docker.argvs]


def report(ctx):
    """The test-report.json of the first attempt of task 1."""
    return json.loads((ctx.run.folder / "tasks/1/attempt-1/verify/test-report.json").read_text())


def test_affected_runs_checks_and_picked_tests(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work)
    script_reports(adapters, PASS, PASS)
    res = mod.run(ctx)
    assert res.status == "pass", res.reasons
    first, second = argvs(adapters)
    assert "tests/test_a.py" in first and FILES[0] in second
    data = report(ctx)
    assert data["mode"] == "affected" and data["picked"] == ["tests/test_a.py"] and data["ok"] is True


def test_affected_nothing_picked_runs_checks_only(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work, edit={"notes.txt": "hi\n"})
    script_reports(adapters, PASS)
    assert mod.run(ctx).status == "pass"
    assert len(argvs(adapters)) == 1 and FILES[0] in argvs(adapters)[0]
    assert report(ctx)["mode"] == "checks" and report(ctx)["picked"] == []


def test_affected_all_fallback_runs_the_suite(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work, edit={"pyproject.toml": "x\n"})
    script_reports(adapters, PASS, PASS)
    assert mod.run(ctx).status == "pass"
    first, second = argvs(adapters)
    assert "python3 -m pytest -q --junitxml" in first and FILES[0] not in first and FILES[0] in second
    assert report(ctx)["mode"] == "suite"
    assert state.load(ctx.run.folder)["suite_pending"] == []


def test_checkpoint_fires_on_the_fifth_task_and_resets(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work)
    for k in range(1, 5):
        script_reports(adapters, PASS, PASS)
        ctx.task = {**ctx.task, "number": 1}
        assert mod.run(ctx).status == "pass"
        assert report(ctx)["mode"] == "affected"
        state.update(ctx.run.folder, lambda s, k=k: s.__setitem__(
            "suite_pending", [{"number": i, "title": f"T{i}"} for i in range(2, k + 2)]))
    assert len(state.load(ctx.run.folder)["suite_pending"]) == 4
    adapters.docker.argvs.clear()
    script_reports(adapters, PASS, PASS)
    assert mod.run(ctx).status == "pass"
    assert report(ctx)["mode"] == "suite" and len(argvs(adapters)) == 2
    assert state.load(ctx.run.folder)["suite_pending"] == []
    adapters.docker.argvs.clear()
    script_reports(adapters, PASS, PASS)
    mod.run(ctx)
    assert report(ctx)["mode"] == "affected"
    assert [t["number"] for t in state.load(ctx.run.folder)["suite_pending"]] == [1]


def test_suite_every_zero_never_fires(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work, every=0)
    state.update(ctx.run.folder, lambda s: s.__setitem__(
        "suite_pending", [{"number": i, "title": "t"} for i in range(2, 50)]))
    script_reports(adapters, PASS, PASS)
    assert mod.run(ctx).status == "pass"
    assert report(ctx)["mode"] == "affected"


def test_counter_survives_a_reload_of_state(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work)
    script_reports(adapters, PASS, PASS)
    assert mod.run(ctx).status == "pass"
    on_disk = json.loads((ctx.run.folder / "state.json").read_text())
    assert on_disk["suite_pending"] == [{"number": 1, "title": "Add a"}]
    assert mod._pending(ctx) == on_disk["suite_pending"]


def test_checkpoint_failure_names_the_tasks(tmp_path, adapters, work):
    ctx = make(tmp_path, adapters, work, every=3)
    state.update(ctx.run.folder, lambda s: s.__setitem__(
        "suite_pending", [{"number": 7, "title": "Seven"}, {"number": 8, "title": "Eight"}]))
    script_reports(adapters, FAIL, PASS)
    res = mod.run(ctx)
    assert res.status == "fail"
    assert "any task since the last whole-suite pass" in res.reasons[0]
    assert "task 7 (Seven)" in res.reasons[0] and "task 8 (Eight)" in res.reasons[0] and "task 1 (Add a)" in res.reasons[0]
    assert len(state.load(ctx.run.folder)["suite_pending"]) == 2      # a failed checkpoint resets nothing
