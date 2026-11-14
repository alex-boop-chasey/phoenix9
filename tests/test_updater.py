"""The updater (phase 4 prologue 2): install, health check, rollback, recovery, status.

Layout per test: tmp/origin.git (bare; v9.0, v9.1, v9.2 where v9.2 touches image/), tmp/opt/phoenix9
cloned from it at v9.0 (PHOENIX_INSTALL), a temp PHOENIX_HOME. Git is real; check.sh, pnpm, phoenix
doctor / images and systemctl go through the fake host; the clock is the fake clock.
"""
import ast
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from phoenix9 import atomic, events, hold, paths, scrub, state, updater
from phoenix9.git import GitError

REPO = Path(__file__).resolve().parent.parent


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
                           "-c", "init.defaultBranch=main", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def make_origin(tmp: Path, web: bool = False, units: dict | None = None) -> Path:
    """A bare repo with releases v9.0, v9.1 (web/ when asked) and v9.2 (touches image/);
    `units` = {release number: {unit file name: text}} written to deploy/ in that release."""
    work = tmp / "src"
    work.mkdir()
    git(work, "init", "-q")
    (work / "bin").mkdir()
    (work / "bin" / "phoenix").write_text("#!/bin/sh\n")
    (work / "image").mkdir()
    (work / "image" / "Dockerfile").write_text("FROM scratch\n")
    for n in (0, 1, 2):
        (work / "VERSION").write_text(f"v9.{n}\n")
        if n == 1 and web:
            (work / "web").mkdir()
            (work / "web" / "package.json").write_text("{}\n")
        if n == 2:
            (work / "image" / "Dockerfile").write_text("FROM scratch\nRUN true\n")
        for name, text in ((units or {}).get(n) or {}).items():
            (work / "deploy").mkdir(exist_ok=True)
            (work / "deploy" / name).write_text(text)
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", f"release {n}")
        git(work, "tag", f"v9.{n}")
    origin = tmp / "origin.git"
    git(tmp, "clone", "-q", "--bare", str(work), str(origin))
    return origin


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """origin.git + tmp/opt/phoenix9 at v9.0."""
    origin = make_origin(tmp_path)
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    return {"origin": origin, "install": inst, **{k: v for k, v in updater.folders().items() if k != "install"}}


def head(folder) -> str:
    return git(folder, "rev-parse", "HEAD")


def tag_commit(layout, tag) -> str:
    return git(layout["origin"], "rev-parse", f"{tag}^{{commit}}")


def no_marker(layout, tag) -> bool:
    """True when no copy of Phoenix carries the updater's pre-<tag> marker."""
    folders = [layout[k] for k in ("install", "prev", "next", "failed") if (layout[k] / ".git").exists()]
    return all(f"pre-{tag}" not in git(f, "tag").split() for f in folders)


def doctor(layout=None):
    return [str(paths.install() / "bin" / "phoenix"), "doctor"]


def restarts(adapters):
    return [c for c in adapters.host.calls if c[:2] == ["systemctl", "restart"]]


def systemctl_calls(adapters):
    return [c for c in adapters.host.calls if c[:1] == ["systemctl"]]


def update_events():
    return [e["type"] for e in events.read(paths.events()) if e["type"].startswith("update.")]


def hold_left() -> bool:
    """The hold file is still there (hold_requested() is False anyway once the updater's lock is free)."""
    return (paths.home() / "update" / "hold").exists()


@contextlib.contextmanager
def other_update():
    """Another updater holds HOME/update/lock."""
    lock = hold.lock_file()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def killed(monkeypatch):
    """Act out a process killed outright (SIGKILL, power cut): no in-process recovery runs."""
    monkeypatch.setattr(updater, "_recover_after_error", lambda u, error: None)


def make_run(project="proj", run_id="r1", status="running", tasks=7, on=3, held=None):
    run_dir = paths.runs(project) / run_id
    run_dir.mkdir(parents=True)
    st = state.new_state(run_id, project, {str(n): state.new_task(f"t{n}") for n in range(1, tasks + 1)})
    st["status"] = status
    if on:
        st["tasks"][str(on)]["status"] = "running"
    if held is not None:
        st["current"]["held"] = held
    atomic.write_json(run_dir / "state.json", st)
    return run_dir


# 1
def test_install_happy_path(layout, adapters):
    old = head(layout["install"])
    out = updater.install("v9.1", adapters, who="alex")
    assert out["ok"] and out["result"] == "installed" and out["previous"] == "v9.0"
    inst = layout["install"]
    assert head(inst) == tag_commit(layout, "v9.1")
    assert head(layout["prev"]) == old
    assert no_marker(layout, "v9.1")
    calls, cwds = adapters.host.calls, adapters.host.cwds
    i = calls.index(["./check.sh"])
    assert cwds[i] == str(layout["next"])
    assert restarts(adapters) == [["systemctl", "restart", "phoenix-runner", "phoenix-api"]]
    d = [k for k, c in enumerate(calls) if c[:2] == doctor()]
    assert d and calls[d[0]] == doctor() + ["--for-update", "--json"] and cwds[d[0]] == str(inst)
    assert update_events() == ["update.started", "update.installed"]
    assert adapters.notify.messages == ["Phoenix 9 is now v9.1."]
    st = updater.status(adapters)
    assert st["installed"]["tag"] == "v9.1" and st["last"]["result"] == "installed"
    assert not hold_left() and not (paths.home() / "update" / "hold").exists()
    assert not layout["next"].exists() and st["phase"] is None


# 2
def test_failing_tests_stop_before_swap(layout, adapters):
    adapters.host.script(["./check.sh"], rc=1, out="2 failed")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "tests-failed" and not out["ok"]
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert systemctl_calls(adapters) == []
    assert not layout["next"].exists()
    assert "2 failed" in (paths.logs() / "update-v9.1-checks.txt").read_text()
    assert no_marker(layout, "v9.1")
    assert not hold_left()
    assert update_events() == ["update.started", "update.failed"]
    assert len(adapters.notify.messages) == 1


# 3
def test_web_build_runs_before_tests_when_web_exists(tmp_path, monkeypatch, adapters):
    origin = make_origin(tmp_path, web=True)
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    seq = [c for c in adapters.host.calls if c[0] in ("pnpm", "./check.sh")]
    assert seq == [["pnpm", "-C", "web", "install", "--frozen-lockfile"], ["pnpm", "-C", "web", "build"],
                   ["./check.sh"]]
    # a failing build stops it (go back to v9.0 first)
    assert updater.rollback(adapters, who="alex")["result"] == "rolled-back-manual"
    adapters.host.script(["pnpm", "-C", "web", "build"], rc=1, err="tsc error")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "tests-failed" and head(inst) == git(origin, "rev-parse", "v9.0^{commit}")


# 4
def test_failed_health_swaps_back(layout, adapters):
    bad = (1, "ok api\nFAIL runner: not running\n", "")
    adapters.host.script_seq(doctor(), [bad, bad, bad, (0, "all good", "")])
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "rolled-back" and not out["ok"]
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert head(layout["failed"]) == tag_commit(layout, "v9.1")
    assert no_marker(layout, "v9.1")
    assert len(restarts(adapters)) == 2
    assert update_events() == ["update.started", "update.rolledback"]
    assert len(adapters.notify.messages) == 1 and "FAIL runner: not running" in adapters.notify.messages[0]
    assert adapters.clock.sleeps.count(updater.HEALTH_GAP_S) == 2
    assert not hold_left()


# 5
def test_rolled_back_unhealthy_notifies_urgently(layout, adapters):
    adapters.host.script(doctor(), rc=1, out="FAIL api: no answer")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "rolled-back-unhealthy"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert layout["failed"].exists() and len(restarts(adapters)) == 2
    (msg,) = adapters.notify.messages
    assert msg.startswith("URGENT") and "may be down" in msg
    assert update_events()[-1] == "update.rolledback" and not hold_left()


# 6
def test_busy_harness_waits_then_proceeds_at_task_boundary(layout, adapters):
    run_dir = make_run(on=2)
    seen = []
    real_sleep = adapters.clock.sleep

    def sleep(s):
        if s == updater.POLL_S:
            seen.append((hold.hold_requested(), updater.status(adapters)["waiting"]))
            if len(seen) == 3:      # the runner reaches its task boundary
                state.update(run_dir, lambda st: st["current"].__setitem__("held", True))
        real_sleep(s)
    adapters.clock.sleep = sleep
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "installed"
    assert len(seen) == 3 and all(h for h, _ in seen)
    assert seen[0][1] == "waiting: run r1 (proj) is on task 2 of 7"
    assert not hold_left()


# 7
def test_busy_timeout_gives_up_without_swap(layout, adapters):
    make_run()
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "harness-busy" and "task 3 of 7" in out["reason"]
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and not hold_left()
    assert systemctl_calls(adapters) == []
    assert adapters.clock.now() - 1000.0 >= 120 * 60


# 12
def test_rollback_command(layout, adapters):
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    adapters.host.calls.clear()
    out = updater.rollback(adapters, who="alex")
    assert out["result"] == "rolled-back-manual" and out["tag"] == "v9.0" and out["previous"] == "v9.1"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert head(layout["prev"]) == tag_commit(layout, "v9.1")
    assert len(restarts(adapters)) == 1
    assert any(c[:2] == doctor() for c in adapters.host.calls)
    assert update_events()[-1] == "update.rolledback"
    assert updater.rollback(adapters, who="alex")["result"] == "rolled-back-manual"
    assert head(layout["install"]) == tag_commit(layout, "v9.1")
    assert head(layout["prev"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and not hold_left()


def test_unhealthy_rollback_swaps_back_and_refuses(layout, adapters):
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    adapters.host.script(doctor(), rc=1, out="FAIL api")
    out = updater.rollback(adapters, who="alex")
    assert out["result"] == "refused" and "FAIL api" in out["reason"]
    assert head(layout["install"]) == tag_commit(layout, "v9.1")
    assert head(layout["prev"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and not hold_left()


# 13
def test_rollback_without_previous_refused(layout, adapters):
    out = updater.rollback(adapters, who="alex")
    assert out["result"] == "refused" and out["reason"] == "nothing to roll back to"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert systemctl_calls(adapters) == []


# 14
def test_status_report(tmp_path, monkeypatch, adapters):
    monkeypatch.setenv("PHOENIX_INSTALL", str(tmp_path / "nowhere"))
    fresh = updater.status(adapters)
    assert fresh["supported"] is True and fresh["installed"] is None and fresh["can_rollback"] is False
    origin = make_origin(tmp_path)
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    st = updater.status(adapters)
    assert st["installed"]["tag"] == "v9.1" and st["previous"]["tag"] == "v9.0" and st["can_rollback"]
    assert st["newest"] is None and not st["update_available"]
    st = updater.status(adapters, refresh=True)
    assert st["newest"] == "v9.2" and st["update_available"]
    assert updater.status(adapters)["newest"] == "v9.2"     # cached
    make_run(on=4)
    st = updater.status(adapters)
    assert st["busy"] and st["busy_reason"] == "run r1 (proj) is on task 4 of 7"
    assert st["log_tail"] and "installed" in st["log_tail"][-1]
    assert st["last"]["result"] == "installed" and st["last"]["who"] == "alex"
    assert st["running"] is False


# 15
@pytest.mark.parametrize("tag", ["main", "v8.1", "v9.01", "v9.1;rm -rf /", "--upload-pack=x", "v9.1 ", "v9.1\n",
                                 "", None])
def test_bad_tag_refused(layout, adapters, tag, monkeypatch):
    seen = []
    monkeypatch.setattr(adapters, "git", type("G", (), {"git": lambda self, *a, **k: seen.append(a)})())
    out = updater.install(tag, adapters, who="alex")
    assert out["result"] == "refused" and not out["ok"]
    assert seen == [] and adapters.host.calls == []
    out = updater.request("install", tag, "alex", adapters)
    assert out["result"] == "refused" and adapters.host.calls == []
    assert not (paths.home() / "update" / "request.json").exists()


# 16
def test_same_tag_is_noop(layout, adapters):
    out = updater.install("v9.0", adapters, who="alex")
    assert out["ok"] and out["result"] == "already-installed"
    assert adapters.host.calls == [] and not layout["prev"].exists() and update_events() == []
    assert "pre-v9.0" not in git(layout["install"], "tag")


# 17
def test_second_update_refused_while_locked(layout, adapters, monkeypatch):
    import fcntl
    monkeypatch.setattr(updater, "LOCK_WAIT_S", 0.1)
    lock = paths.home() / "update" / "lock"
    lock.parent.mkdir(parents=True)
    with open(lock, "a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = updater.install("v9.1", adapters, who="alex")
        assert out["result"] == "refused" and "another update" in out["reason"]
        assert updater.rollback(adapters, who="alex")["result"] == "refused"
        assert updater.request("install", "v9.1", "alex", adapters)["result"] == "refused"
        assert updater.status(adapters)["running"] is True
        atomic.write_json(paths.home() / "update" / "request.json", {"action": "install", "tag": "v9.1", "who": "x"})
        assert updater.run_request(adapters)["result"] == "refused"
        assert (paths.home() / "update" / "request.json").exists()    # lock first: not taken from the running one
    assert head(layout["install"]) == tag_commit(layout, "v9.0") and adapters.host.calls == []


# 18
@pytest.mark.parametrize("next_left", [True, False])
def test_recover_half_swap(layout, adapters, next_left):
    """Crash after `rename(install, prev)`: the next run puts the old copy back first, then does the request."""
    inst, old = layout["install"], head(layout["install"])
    if next_left:
        git(inst, "clone", "-q", "--no-hardlinks", str(inst), str(layout["next"]))
    inst.rename(layout["prev"])
    job = {"kind": "install", "tag": "v9.1", "who": "alex", "phase": "swapping",
           "from": {"tag": "v9.0", "commit": old}, "to": {"tag": "v9.1", "commit": tag_commit(layout, "v9.1")}}
    atomic.write_json(paths.home() / "update" / "status.json", {"job": job})
    hold.request_hold("update to v9.1")
    assert updater.request("install", "v9.1", "alex", adapters)["queued"]
    out = updater.run_request(adapters)
    assert out["result"] == "installed" and out["reason"].startswith("recovered first")
    assert head(inst) == tag_commit(layout, "v9.1") and head(layout["prev"]) == old
    first_restart = adapters.host.calls.index(["systemctl", "restart", "phoenix-runner", "phoenix-api"])
    assert first_restart < adapters.host.calls.index(["./check.sh"])   # restored before the request ran
    assert not (paths.home() / "update" / "request.json").exists()


# 19
def test_images_rebuilt_only_when_image_files_changed(layout, adapters):
    def images():
        return [(c, w) for c, w in zip(adapters.host.calls, adapters.host.cwds) if c[1:3] == ["images", "build"]]
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert images() == []
    adapters.host.script_seq([str(layout["next"] / "bin" / "phoenix"), "images"], [(1, "", "build failed")])
    out = updater.install("v9.2", adapters, who="alex")
    assert out["result"] == "images-failed" and head(layout["install"]) == tag_commit(layout, "v9.1")
    assert not layout["next"].exists() and len(restarts(adapters)) == 1
    adapters.host.script([str(layout["next"] / "bin" / "phoenix"), "images"], rc=0)
    assert updater.install("v9.2", adapters, who="alex")["result"] == "installed"
    calls = images()
    assert len(calls) == 2
    assert calls[-1][0] == [str(layout["next"] / "bin" / "phoenix"), "images", "build", "--changed", "--json"]
    assert calls[-1][1] == str(layout["next"])


# 20
def test_request_writes_file_and_starts_unit_no_block(layout, adapters):
    out = updater.request("install", "v9.1", "dashboard", adapters)
    assert out["ok"] and out["queued"]
    req = atomic.read_json(paths.home() / "update" / "request.json")
    assert req["action"] == "install" and req["tag"] == "v9.1" and req["who"] == "dashboard" and req["at"]
    assert adapters.host.calls == [["systemctl", "start", "--no-block", "phoenix9-update.service"]]
    assert updater.request("rollback", "v9.1", "cli", adapters)["tag"] is None
    assert updater.request("delete", None, "cli", adapters)["result"] == "refused"
    out = updater.run_request(adapters)       # the rollback request: nothing to roll back to
    assert out["result"] == "refused" and not (paths.home() / "update" / "request.json").exists()


# 21
def test_updater_log_scrubbed(layout, adapters):
    secret = "sk-ant-SUPERSECRETVALUE123"
    scrub.add_secrets([secret])
    adapters.host.script(["./check.sh"], rc=1, out=f"token={secret}")
    adapters.host.script(doctor(), rc=1, out=f"FAIL leaked {secret}")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "tests-failed"
    adapters.host.script(["./check.sh"], rc=0)
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "rolled-back-unhealthy"
    texts = [(paths.logs() / "updater.log").read_text(), json.dumps(updater.status(adapters)),
             json.dumps(out), *adapters.notify.messages, (paths.logs() / "update-v9.1-checks.txt").read_text(),
             paths.events().read_text()]
    assert all(secret not in t for t in texts)
    assert "[secret]" in "".join(adapters.notify.messages)


# 22
def test_updater_imports_only_allowed_modules():
    tree = ast.parse((REPO / "phoenix9" / "updater.py").read_text())
    allowed = {"paths", "atomic", "adapters", "events", "scrub", "hold"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = [n for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom))]
            assert inner == [], f"import inside {node.name}"
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in sys.stdlib_module_names for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "phoenix9":
                assert {a.name for a in node.names} <= allowed
            else:
                assert node.module.split(".")[0] in sys.stdlib_module_names, node.module
    hold_tree = ast.parse((REPO / "phoenix9" / "hold.py").read_text())
    mods = {a.name for n in ast.walk(hold_tree) if isinstance(n, ast.ImportFrom) and n.module == "phoenix9"
            for a in n.names}
    assert mods <= {"paths", "atomic", "state"}


# ------------------------------------------------------------------ the phase machine on its own
def test_transition_table_is_a_single_path():
    for kind, table in updater.TRANSITIONS.items():
        phase, seen = None, []
        while table.get(phase):
            phase = table[phase][0]
            if phase in seen:
                break
            seen.append(phase)
        assert set(seen) == {p for p in table if p}, kind
        assert set(updater._RECOVERY) == set(updater.TRANSITIONS)


def test_phase_refuses_a_jump(layout, adapters):
    u = updater._Update(adapters, "t")
    u.start("install", "v9.1", {"tag": "v9.0", "commit": "x"}, {"tag": "v9.1", "commit": "y"}, "preparing")
    with pytest.raises(RuntimeError):
        u.phase("swapped")
    with pytest.raises(RuntimeError):
        updater._Update(adapters, "t").start("rollback", "v9.0", {}, {}, "swapping")


REAL_RECOVER_AFTER_ERROR = updater._recover_after_error


class Crash(BaseException):
    """Stands in for the updater process dying (not caught by `except Exception`)."""


INSTALL_PHASES = ["preparing", "waiting", "swapping", "swapped", "restarted", "restoring"]


@pytest.mark.parametrize("phase", INSTALL_PHASES)
def test_install_crash_at_any_phase_recovers_old_version(layout, adapters, monkeypatch, phase):
    """Die right after a phase is saved; the next run restores v9.0 and leaves no hold."""
    if phase == "restoring":
        adapters.host.script(doctor(), rc=1, out="FAIL")
    real = updater._Update.phase

    def phase_then_die(self, name, **extra):
        real(self, name, **extra)
        if name == phase:
            raise Crash(name)
    monkeypatch.setattr(updater._Update, "phase", phase_then_die)
    killed(monkeypatch)
    with pytest.raises(Crash):
        updater.install("v9.1", adapters, who="alex")
    monkeypatch.setattr(updater._Update, "phase", real)
    monkeypatch.setattr(updater, "_recover_after_error", REAL_RECOVER_AFTER_ERROR)
    assert updater.status(adapters)["interrupted"]
    adapters.host.calls.clear()
    out = updater.recover(adapters)
    assert out["result"] == "recovered"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and not hold_left()
    assert updater.status(adapters)["phase"] is None
    moved = phase not in ("preparing", "waiting")
    assert bool(restarts(adapters)) == moved
    assert updater.recover(adapters) is None          # nothing left to do
    assert no_marker(layout, "v9.1")
    adapters.host.script(doctor(), rc=0)
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"


@pytest.mark.parametrize("nth", [1, 2])
def test_install_crash_between_renames_recovers(layout, adapters, monkeypatch, nth):
    """Die on the 1st or 2nd folder rename of the swap."""
    real, count = updater._rename, [0]

    def rename(src, dst):
        count[0] += 1
        if count[0] == nth:
            raise Crash("power cut")
        real(src, dst)
    monkeypatch.setattr(updater, "_rename", rename)
    killed(monkeypatch)
    with pytest.raises(Crash):
        updater.install("v9.1", adapters, who="alex")
    monkeypatch.setattr(updater, "_rename", real)
    monkeypatch.setattr(updater, "_recover_after_error", REAL_RECOVER_AFTER_ERROR)
    assert updater.recover(adapters)["result"] == "recovered"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert not hold_left()


ROLLBACK_STOPS = [("waiting", False), ("staged", False), ("swapping", False), ("swapped", False),
                  ("restarted", False), ("staged", True), ("swapping", True), ("swapped", True)]


@pytest.mark.parametrize("phase,reverting", ROLLBACK_STOPS)
def test_rollback_crash_at_any_phase_keeps_where_it_was(layout, adapters, monkeypatch, phase, reverting):
    """A rollback that dies anywhere (also while swapping back) ends with v9.1 installed and v9.0 as -prev."""
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    if reverting:
        adapters.host.script(doctor(), rc=1, out="FAIL")
    real = updater._Update.phase

    def phase_then_die(self, name, **extra):
        real(self, name, **extra)
        if name == phase and bool(self.job.get("reverting")) == reverting:
            raise Crash(name)
    monkeypatch.setattr(updater._Update, "phase", phase_then_die)
    killed(monkeypatch)
    with pytest.raises(Crash):
        updater.rollback(adapters, who="alex")
    monkeypatch.setattr(updater._Update, "phase", real)
    monkeypatch.setattr(updater, "_recover_after_error", REAL_RECOVER_AFTER_ERROR)
    assert updater.recover(adapters)["result"] == "recovered"
    assert head(layout["install"]) == tag_commit(layout, "v9.1")
    assert head(layout["prev"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and not hold_left()


def test_unexpected_error_mid_swap_is_recovered_at_once(layout, adapters, monkeypatch):
    real, count = updater._rename, [0]

    def rename(src, dst):
        count[0] += 1
        if count[0] == 2:
            raise OSError("disk full")
        real(src, dst)
    monkeypatch.setattr(updater, "_rename", rename)
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "recovered" and not out["ok"]
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert not hold_left() and updater.status(adapters)["phase"] is None


def test_missing_install_with_prev_is_restored_without_a_job(layout, adapters):
    layout["install"].rename(layout["prev"])
    assert updater.recover(adapters)["result"] == "recovered"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")


def test_main_runs_the_request(layout, adapters, monkeypatch, capsys):
    monkeypatch.setattr(updater.adapters_mod, "real", lambda: adapters)
    monkeypatch.setattr(updater.signal, "signal", lambda *a: None)
    updater.request("install", "v9.1", "cli", adapters)
    assert updater.main(["run-request"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "installed"
    assert updater.main(["nonsense"]) == 2


# ------------------------------------------------------------------ critic's fixes and decisions
def test_sigterm_mid_update_recovers_then_stops(layout, adapters, monkeypatch):
    """systemd's SIGTERM (SystemExit from main's handler) after the swap: put v9.0 back, then exit 143."""
    monkeypatch.setattr(updater.adapters_mod, "real", lambda: adapters)
    real_run = adapters.host.run

    def run(argv, timeout=60, cwd=None):
        if argv[1:2] == ["doctor"]:
            os.kill(os.getpid(), signal.SIGTERM)
        return real_run(argv, timeout=timeout, cwd=cwd)
    adapters.host.run = run
    updater.request("install", "v9.1", "cli", adapters)
    before = signal.getsignal(signal.SIGTERM)
    try:
        with pytest.raises(SystemExit) as exc:
            updater.main(["run-request"])
    finally:
        signal.signal(signal.SIGTERM, before)
    assert exc.value.code == 143
    assert head(layout["install"]) == tag_commit(layout, "v9.0")
    assert head(layout["failed"]) == tag_commit(layout, "v9.1")
    assert len(restarts(adapters)) == 2           # after the swap, and after putting v9.0 back
    st = updater.status(adapters)
    assert st["phase"] is None and not st["interrupted"] and st["last"]["result"] == "recovered"
    assert not hold_left()


def test_keyboard_interrupt_before_swap_is_cleaned_up_and_passed_on(layout, adapters):
    adapters.host.script(["./check.sh"], rc=0)
    real_run = adapters.host.run

    def run(argv, timeout=60, cwd=None):
        if argv == ["./check.sh"]:
            raise KeyboardInterrupt
        return real_run(argv, timeout=timeout, cwd=cwd)
    adapters.host.run = run
    with pytest.raises(KeyboardInterrupt):
        updater.install("v9.1", adapters, who="alex")
    assert head(layout["install"]) == tag_commit(layout, "v9.0") and not layout["next"].exists()
    assert updater.status(adapters)["phase"] is None and systemctl_calls(adapters) == []


def failing_git(adapters, monkeypatch, word):
    """Make the git adapter fail on one git subcommand."""
    real = adapters.git.git

    def git_(cwd, *args, **kw):
        if word in args:
            raise GitError(f"git {word} failed: boom")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(adapters.git, "git", git_)


def test_image_diff_git_failure_is_not_nothing_changed(layout, adapters, monkeypatch):
    """A failing `git diff` must stop the update, not skip the image rebuild."""
    failing_git(adapters, monkeypatch, "diff")
    out = updater.install("v9.2", adapters, who="alex")
    assert out["result"] == "refused" and "git diff failed" in out["reason"]
    assert not any(c[1:3] == ["images", "build"] for c in adapters.host.calls)
    assert head(layout["install"]) == tag_commit(layout, "v9.0") and not layout["next"].exists()
    assert systemctl_calls(adapters) == [] and not hold_left()
    assert update_events() == ["update.started", "update.failed"]


def test_crash_while_preparing_reports_refused_with_the_error(layout, adapters, monkeypatch):
    """Clone fails: nothing moved, so the result is `refused` with the error text (not `recovered`)."""
    failing_git(adapters, monkeypatch, "clone")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "refused" and "git clone failed: boom" in out["reason"]
    assert updater.status(adapters)["last"]["result"] == "refused"
    assert head(layout["install"]) == tag_commit(layout, "v9.0") and not layout["next"].exists()
    assert systemctl_calls(adapters) == [] and updater.status(adapters)["phase"] is None
    assert len(adapters.notify.messages) == 1 and "Nothing was changed" in adapters.notify.messages[0]


def test_already_installed_compares_commits_not_tags(layout, adapters):
    """HEAD at v9.1's commit but untagged locally (`unknown`): installing v9.1 is a no-op."""
    inst = layout["install"]
    git(inst, "checkout", "-q", "--detach", "v9.1")
    git(inst, "tag", "-d", "v9.1", "v9.2")
    assert updater.status(adapters)["installed"]["tag"] == "unknown"
    out = updater.install("v9.1", adapters, who="alex")
    assert out["ok"] and out["result"] == "already-installed"
    assert adapters.host.calls == [] and not layout["prev"].exists() and update_events() == []


def test_release_tag_moved_on_origin_is_refused(layout, adapters):
    """Fetch has no --force: a v9.1 that now points elsewhere on origin is refused, nothing touched."""
    git(layout["origin"], "tag", "-f", "v9.1", "v9.2^{commit}")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "refused" and out["reason"] == "release v9.1 changed on origin"
    assert adapters.host.calls == [] and not layout["next"].exists()
    assert head(layout["install"]) == tag_commit(layout, "v9.0") and update_events() == []
    assert git(layout["install"], "rev-parse", "v9.1^{commit}") != tag_commit(layout, "v9.1")


def test_images_rebuilt_after_the_harness_is_idle(layout, adapters):
    seen = []
    real_run = adapters.host.run

    def run(argv, timeout=60, cwd=None):
        if argv[1:3] == ["images", "build"]:
            seen.append((hold.hold_requested(), updater._read_status()["job"]["phase"]))
        return real_run(argv, timeout=timeout, cwd=cwd)
    adapters.host.run = run
    adapters.host.script([str(layout["next"] / "bin" / "phoenix"), "images"], rc=1, err="no")
    out = updater.install("v9.2", adapters, who="alex")
    assert out["result"] == "images-failed" and seen == [(True, "waiting")]
    assert not hold_left() and not layout["next"].exists() and systemctl_calls(adapters) == []
    assert update_events() == ["update.started", "update.failed"]


def test_status_interrupted_and_lock_probe_read_only(layout, adapters):
    lock = hold.lock_file()
    st = updater.status(adapters)
    assert st["running"] is False and st["interrupted"] is False and not lock.exists()
    job = {"kind": "install", "tag": "v9.1", "who": "alex", "phase": "swapping",
           "from": {"tag": "v9.0", "commit": head(layout["install"])}, "to": {"tag": "v9.1", "commit": "x"}}
    atomic.write_json(paths.home() / "update" / "status.json", {"job": job})
    assert updater.status(adapters)["interrupted"] is True
    with other_update():
        st = updater.status(adapters)
        assert st["running"] is True and st["interrupted"] is False


def test_request_recover(layout, adapters):
    out = updater.request("recover", "v9.1", "dashboard", adapters)
    assert out["ok"] and out["queued"] and out["tag"] is None
    assert atomic.read_json(paths.home() / "update" / "request.json")["action"] == "recover"
    out = updater.run_request(adapters)
    assert out["ok"] and out["result"] == "recovered" and out["reason"] == "nothing needed repairing"
    layout["install"].rename(layout["prev"])
    updater.request("recover", None, "dashboard", adapters)
    out = updater.run_request(adapters)
    assert out["result"] == "recovered" and head(layout["install"]) == tag_commit(layout, "v9.0")


SECRET_ENV = "PHOENIX_TEST_TOKEN=envfile-secret-value-42\n"


@pytest.mark.parametrize("call", ["install", "rollback", "recover", "request", "run_request", "status"])
def test_every_public_call_loads_the_secret_files(layout, adapters, monkeypatch, call):
    monkeypatch.setattr(scrub, "_GLOBAL", scrub.Scrubber())
    paths.secrets().mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "global.env").write_text(SECRET_ENV)
    {"install": lambda: updater.install("v9.0", adapters, who="t"),
     "rollback": lambda: updater.rollback(adapters, who="t"),
     "recover": lambda: updater.recover(adapters),
     "request": lambda: updater.request("rollback", None, "t", adapters),
     "run_request": lambda: updater.run_request(adapters),
     "status": lambda: updater.status(adapters)}[call]()
    assert "envfile-secret-value-42" in scrub.known_secrets()


def test_secret_from_env_file_never_reaches_the_log(layout, adapters, monkeypatch):
    monkeypatch.setattr(scrub, "_GLOBAL", scrub.Scrubber())
    paths.secrets().mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "global.env").write_text(SECRET_ENV)
    adapters.host.script(["./check.sh"], rc=1, out="leak envfile-secret-value-42")
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "tests-failed"
    texts = [(paths.logs() / "updater.log").read_text(), (paths.logs() / "update-v9.1-checks.txt").read_text(),
             *adapters.notify.messages, json.dumps(out)]
    assert all("envfile-secret-value-42" not in t for t in texts)


# ------------------------------------------------------------------ review fixes (2026-11-01)
def test_moved_unrelated_tag_does_not_block_a_new_release(layout, adapters):
    """Only the requested tag is fetched: an old tag that moved on origin no longer blocks every update."""
    origin, work = layout["origin"], layout["origin"].parent / "src"
    git(origin, "tag", "-f", "v9.1", "v9.2^{commit}")          # an old, unrelated release moved
    (work / "VERSION").write_text("v9.3\n")
    git(work, "commit", "-q", "-am", "release 3")
    git(work, "tag", "v9.3")
    git(work, "push", "-q", str(origin), "HEAD:refs/heads/main", "v9.3")
    out = updater.install("v9.3", adapters, who="alex")
    assert out["result"] == "installed", out["reason"]
    assert head(layout["install"]) == tag_commit(layout, "v9.3")
    # the local copy of the moved tag is untouched (never forced)
    assert git(layout["install"], "rev-parse", "v9.1^{commit}") != tag_commit(layout, "v9.1")


def kill_rollback_at(adapters, monkeypatch, phase):
    real = updater._Update.phase

    def phase_then_die(self, name, **extra):
        real(self, name, **extra)
        if name == phase:
            raise Crash(name)
    monkeypatch.setattr(updater._Update, "phase", phase_then_die)
    killed(monkeypatch)
    with pytest.raises(Crash):
        updater.rollback(adapters, who="alex")
    monkeypatch.setattr(updater._Update, "phase", real)
    monkeypatch.setattr(updater, "_recover_after_error", REAL_RECOVER_AFTER_ERROR)


@pytest.mark.parametrize("phase", ["waiting", "staged"])
def test_rollback_killed_before_swap_with_unreadable_git_only_unstages(layout, adapters, monkeypatch, phase):
    """Killed at waiting/staged and git cannot read the installed copy: recovery must not swap anything in."""
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    kill_rollback_at(adapters, monkeypatch, phase)
    failing_git(adapters, monkeypatch, "rev-parse")
    adapters.host.calls.clear()
    out = updater.recover(adapters)
    assert out["result"] == "recovered"
    assert head(layout["install"]) == tag_commit(layout, "v9.1")
    assert head(layout["prev"]) == tag_commit(layout, "v9.0")
    assert not layout["next"].exists() and restarts(adapters) == []
    assert updater.status(adapters)["phase"] is None


def test_rollback_recovery_after_swap_with_unreadable_git_needs_a_person(layout, adapters, monkeypatch):
    """Killed after the swap and the installed version cannot be read: move nothing, keep the job, tell Alex."""
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    kill_rollback_at(adapters, monkeypatch, "swapped")
    assert head(layout["install"]) == tag_commit(layout, "v9.0")    # the unconfirmed rollback target
    failing_git(adapters, monkeypatch, "rev-parse")
    adapters.host.calls.clear()
    adapters.notify.messages.clear()
    out = updater.recover(adapters)
    assert not out["ok"] and out["result"] == "needs-person"
    assert out["reason"] == "recovery needs a person: could not read the installed version"
    assert head(layout["install"]) == tag_commit(layout, "v9.0")    # nothing moved
    assert head(layout["prev"]) == tag_commit(layout, "v9.1") and not layout["next"].exists()
    assert restarts(adapters) == []
    st = updater.status(adapters)
    assert st["interrupted"] and st["phase"] == "swapped" and st["last"]["result"] == "needs-person"
    assert len(adapters.notify.messages) == 1 and "needs a person" in adapters.notify.messages[0]
    # a new install does not run over the unresolved job
    out = updater.install("v9.2", adapters, who="alex")
    assert out["result"] == "needs-person" and head(layout["install"]) == tag_commit(layout, "v9.0")
    assert not any(c == ["./check.sh"] for c in adapters.host.calls)


def test_rollback_refused_when_installed_version_unreadable(layout, adapters, monkeypatch):
    """A rollback never starts with an unknown `from` commit (recovery could not tell which way to go)."""
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    real = adapters.git.git

    def git_(cwd, *args, **kw):
        if "rev-parse" in args and Path(cwd) == layout["install"]:
            raise GitError("git rev-parse failed: boom")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(adapters.git, "git", git_)
    adapters.host.calls.clear()
    out = updater.rollback(adapters, who="alex")
    assert out["result"] == "refused" and "could not read the installed version" in out["reason"]
    assert head(layout["install"]) == tag_commit(layout, "v9.1") and restarts(adapters) == []
    assert updater.status(adapters)["phase"] is None


def test_update_lock_waits_out_a_brief_status_probe(layout, adapters):
    """A status check's shared lock for a moment must not make the starting update refuse."""
    import threading
    lock = hold.lock_file()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    fd = open(lock, "rb")
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    threading.Timer(0.3, fd.close).start()
    atomic.write_json(paths.home() / "update" / "request.json", {"action": "recover", "tag": None, "who": "x"})
    out = updater.run_request(adapters)
    assert out["ok"] and out["result"] == "recovered", out["reason"]


def test_refused_run_request_is_recorded_as_last(layout, adapters, monkeypatch):
    """The app must not show `queued` forever: a refused run_request becomes status `last`."""
    monkeypatch.setattr(updater, "LOCK_WAIT_S", 0.1)
    atomic.write_json(paths.home() / "update" / "request.json", {"action": "install", "tag": "v9.1", "who": "alex"})
    with other_update():
        out = updater.run_request(adapters)
    assert out["result"] == "refused"
    last = updater.status(adapters)["last"]
    assert last["result"] == "refused" and last["reason"] == "another update is running"
    assert last["action"] == "install" and last["tag"] == "v9.1" and last["who"] == "alex"
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert updater.status(adapters)["last"]["result"] == "installed"     # a later result replaces it


def test_healthy_install_runs_the_new_copys_one_time_migrations(layout, adapters):
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "installed"
    inst = layout["install"]
    migrate = [str(inst / "bin" / "phoenix"), "settings", "global", "migrate", "--json"]
    k = adapters.host.calls.index(migrate)
    assert adapters.host.cwds[k] == str(inst)
    assert k > max(i for i, c in enumerate(adapters.host.calls) if c[:2] == doctor())   # after the health check


def test_a_failing_migration_is_only_a_log_line(layout, adapters):
    adapters.host.script([str(layout["install"] / "bin" / "phoenix"), "settings"], rc=1, err="boom")
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert "post-install migration failed" in (paths.logs() / "updater.log").read_text()


# ------------------------------------------------------------------ unit files
UNITS_V0 = {"phoenix-api.service": "[Service]\nExecStart=api\n",
            "phoenix-runner.service": "[Service]\nExecStart=runner\n",
            "phoenix9-update.service": "[Service]\nExecStart=update\n"}
UNITS_V1 = {**UNITS_V0, "phoenix-api.service": "[Service]\nExecStart=api\nEnvironment=HOME=/root\n",
            "phoenix-runner.service": "[Service]\nExecStart=runner\nEnvironment=HOME=/root\n"}


@pytest.fixture
def unit_layout(tmp_path, monkeypatch):
    """Like `layout`, but v9.1 changes the api and runner units; the systemd folder holds v9.0's units."""
    origin = make_origin(tmp_path, units={0: UNITS_V0, 1: UNITS_V1})
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    units = updater.systemd_dir()
    units.mkdir()
    for name, text in UNITS_V0.items():
        (units / name).write_text(text)
    return {"origin": origin, "install": inst, "units": units,
            **{k: v for k, v in updater.folders().items() if k != "install"}}


def installed_units(layout) -> dict:
    return {p.name: p.read_text() for p in layout["units"].iterdir()}


def test_systemd_dir_follows_the_install_script_setting(monkeypatch):
    monkeypatch.delenv("PHOENIX_SYSTEMD_DIR")
    assert updater.systemd_dir() == Path("/etc/systemd/system")
    monkeypatch.setenv("PHOENIX_SYSTEMD_DIR", "/tmp/x")
    assert updater.systemd_dir() == Path("/tmp/x")


def test_install_copies_changed_unit_files_then_reloads_before_restart(unit_layout, adapters):
    out = updater.install("v9.1", adapters, who="alex")
    assert out["result"] == "installed"
    assert installed_units(unit_layout) == UNITS_V1
    assert (unit_layout["units"] / "phoenix-api.service").stat().st_mode & 0o777 == 0o644
    calls = systemctl_calls(adapters)
    assert calls[:2] == [["systemctl", "daemon-reload"], ["systemctl", "restart", "phoenix-runner", "phoenix-api"]]
    log = (paths.logs() / "updater.log").read_text()
    assert "unit file phoenix-api.service updated" in log and "unit file phoenix-runner.service updated" in log
    assert "phoenix9-update.service updated" not in log and "systemctl daemon-reload: exit 0" in log


def test_unchanged_unit_files_are_left_alone(unit_layout, adapters):
    for name, text in UNITS_V1.items():
        (unit_layout["units"] / name).write_text(text)
    before = {p.name: p.stat().st_mtime_ns for p in unit_layout["units"].iterdir()}
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert ["systemctl", "daemon-reload"] not in adapters.host.calls
    assert {p.name: p.stat().st_mtime_ns for p in unit_layout["units"].iterdir()} == before


def test_failed_health_puts_the_old_unit_files_back(unit_layout, adapters):
    bad = (1, "FAIL runner: not running\n", "")
    adapters.host.script_seq(doctor(), [bad, bad, bad, (0, "all good", "")])
    assert updater.install("v9.1", adapters, who="alex")["result"] == "rolled-back"
    assert installed_units(unit_layout) == UNITS_V0
    assert adapters.host.calls.count(["systemctl", "daemon-reload"]) == 2


def test_manual_rollback_restores_the_previous_unit_files(unit_layout, adapters):
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert updater.rollback(adapters, who="alex")["result"] == "rolled-back-manual"
    assert installed_units(unit_layout) == UNITS_V0
    assert updater.rollback(adapters, who="alex")["result"] == "rolled-back-manual"
    assert installed_units(unit_layout) == UNITS_V1


def test_crash_after_swap_recovery_restores_the_old_unit_files(unit_layout, adapters, monkeypatch):
    killed(monkeypatch)
    real = updater._Update.phase

    def phase(self, name, **extra):
        real(self, name, **extra)
        if name == "restarted":
            raise SystemExit(143)
    monkeypatch.setattr(updater._Update, "phase", phase)
    with pytest.raises(SystemExit):
        updater.install("v9.1", adapters, who="alex")
    assert installed_units(unit_layout) == UNITS_V1
    monkeypatch.setattr(updater._Update, "phase", real)
    assert updater.recover(adapters)["result"] == "recovered"
    assert installed_units(unit_layout) == UNITS_V0


def test_install_also_installs_new_unit_files_the_release_ships(tmp_path, monkeypatch, adapters):
    """A unit file new in the release (e.g. claude-rc-chat@.service) is installed too, not only the fixed list."""
    chat = "[Service]\nExecStart=chat %i\n"
    origin = make_origin(tmp_path, units={0: UNITS_V0, 1: {**UNITS_V0, "claude-rc-chat@.service": chat}})
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    units = updater.systemd_dir()
    units.mkdir()
    for name, text in UNITS_V0.items():
        (units / name).write_text(text)
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert (units / "claude-rc-chat@.service").read_text() == chat


def test_install_replaces_a_changed_chat_unit_and_makes_the_launcher_executable(tmp_path, monkeypatch, adapters):
    """A release that changes claude-rc-chat@.service (not in the fixed list) re-installs it; its launcher runs."""
    old, new = "[Service]\nExecStart=claude %i\n", "[Service]\nExecStart=/opt/phoenix9/deploy/chat-launch.sh %i\n"
    origin = make_origin(tmp_path, units={0: {**UNITS_V0, "claude-rc-chat@.service": old},
                                          1: {**UNITS_V0, "claude-rc-chat@.service": new,
                                              "chat-launch.sh": "#!/bin/sh\n"}})
    inst = tmp_path / "opt" / "phoenix9"
    inst.parent.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(inst))
    git(inst, "checkout", "-q", "--detach", "v9.0")
    monkeypatch.setenv("PHOENIX_INSTALL", str(inst))
    units = updater.systemd_dir()
    units.mkdir()
    for name, text in {**UNITS_V0, "claude-rc-chat@.service": old}.items():
        (units / name).write_text(text)
    assert updater.install("v9.1", adapters, who="alex")["result"] == "installed"
    assert (units / "claude-rc-chat@.service").read_text() == new
    assert ["systemctl", "daemon-reload"] in adapters.host.calls
    assert (inst / "deploy" / "chat-launch.sh").stat().st_mode & 0o111
    assert "unit file claude-rc-chat@.service updated" in (paths.logs() / "updater.log").read_text()


def test_recovery_deletes_a_marker_left_by_a_killed_install(layout, adapters, monkeypatch):
    """A killed install never reached its own clean-up; recovery deletes the pre-<tag> marker."""
    def die(*a, **k):
        git(layout["install"], "tag", "-f", "pre-v9.1", "HEAD")      # what a killed process leaves behind
        raise Crash("killed")
    real = updater._drop_marker
    monkeypatch.setattr(updater, "_drop_marker", lambda *a: None)
    monkeypatch.setattr(updater, "_prepare", die)
    killed(monkeypatch)
    with pytest.raises(Crash):
        updater.install("v9.1", adapters, who="alex")
    assert not no_marker(layout, "v9.1")
    monkeypatch.setattr(updater, "_drop_marker", real)
    monkeypatch.setattr(updater, "_recover_after_error", REAL_RECOVER_AFTER_ERROR)
    assert updater.recover(adapters)["result"] == "recovered"
    assert no_marker(layout, "v9.1")


def test_release_tag_ignores_markers_and_old_tags(layout, monkeypatch):
    """The API's health tag is the highest v9.N on HEAD; a stray pre-v9.N marker or other tag never counts."""
    from phoenix9.ops import app
    inst = layout["install"]
    monkeypatch.setenv("PHOENIX_LIBRARY", str(inst))
    for name in ("pre-v9.26", "pre-v9.3", "v8.4", "v9.01"):
        git(inst, "tag", name, "HEAD")
    assert app.release_tag() == "v9.0"
    git(inst, "tag", "v9.10", "HEAD")
    git(inst, "tag", "v9.9", "HEAD")
    assert app.release_tag() == "v9.10"
    for name in ("v9.0", "v9.9", "v9.10"):
        git(inst, "tag", "-d", name)
    assert app.release_tag() == ""
