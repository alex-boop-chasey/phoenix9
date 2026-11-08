"""Tests for Pause now and Resume: the paused run and step, the kept worktree and session, and the resume rules."""
import json
import shutil
from pathlib import Path

import pytest

from fakes import FakeClaude
from phoenix9 import docker, paths, pause, state
from phoenix9.__main__ import main
from phoenix9.claude import Result, build_command
from phoenix9.library import load_library
from phoenix9.ops import common, runs as ops_runs
from phoenix9.ops.common import OpsError
from phoenix9.runner import Runner
from test_runner import REPO, SPEC, add_ai_step, give_profile, lib, make_run, order, project  # noqa: F401  (fixtures)

ONE_TASK = SPEC.split("## Task 2")[0]
SESSION = "0b6f2c1e-4d3a-4f5b-9c8d-7e6f5a4b3c2d"   # Claude session ids are UUIDs


class PausingClaude(FakeClaude):
    """A fake Claude whose first session is cut short by Pause now (like `phoenix run pause --now`)."""

    def __init__(self, run_id_of, session_id=SESSION, keep_session_file=True):
        super().__init__()
        self.run_id_of, self.session_id, self.keep = run_id_of, session_id, keep_session_file
        self.pause_first = True

    def launch(self, docker_, **kw):
        if not (self.pause_first and not self.calls_of_launch()):
            return super().launch(docker_, **kw)
        self.calls.append(("launch", (), kw))
        (Path(kw["workspace"]) / "wip.txt").write_text("half done\n")          # work in progress
        if self.keep:
            claude_dir = Path(kw["prompt_file"]).parent / "claude" / kw["role"] / "-workspace"
            claude_dir.mkdir(parents=True)
            (claude_dir / f"{self.session_id}.jsonl").write_text("{}\n")
        ops_runs.pause(self.run_id_of(), now=True)                              # the container is stopped
        return Result(kind="crashed", session_id=self.session_id)

    def calls_of_launch(self):
        return [c for c in self.calls if c[0] == "launch"]


@pytest.fixture
def setup(tmp_path, project, adapters, lib, monkeypatch):  # noqa: F811
    give_profile(lib, project)
    add_ai_step(lib)
    shutil.rmtree(lib / "steps" / "branch")
    shutil.copytree(REPO / "steps" / "branch", lib / "steps" / "branch")
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    monkeypatch.setattr(common, "library", lambda: load_library(lib))
    adapters.docker.orphans = ["cid-1"]
    run_dir = make_run(tmp_path, spec=ONE_TASK)
    adapters.claude = PausingClaude(lambda: run_dir.name)
    return run_dir, adapters, lib


def reviewer_line(run_dir):
    (line,) = [x for x in state.load(run_dir)["steps"] if x["step"] == "reviewer"]
    return line


def test_pause_stops_the_container_and_pauses_run_and_step(setup):
    run_dir, adapters, lib = setup
    assert Runner(adapters, lib).drive(run_dir) == "paused"
    st = state.load(run_dir)
    assert st["status"] == "paused"
    assert adapters.docker.stopped == ["cid-1"] and "cid-1" not in adapters.docker.removed
    line = reviewer_line(run_dir)
    assert line["status"] == "paused" and line["session_id"] == SESSION
    assert (paths.work("proj", run_dir.name) / "wip.txt").read_text() == "half done\n"   # worktree untouched
    assert pause.requested(run_dir) is None
    assert st["tasks"]["1"]["tries"] == 1


def test_paused_run_is_not_driven_and_frees_the_queue(setup):
    from phoenix9 import watch
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    assert Runner(adapters, lib).drive(run_dir) == "paused"
    other = {"status": "queued", "created": "2026", "run_id": "z", "project": "proj"}
    assert watch.next_run([state.load(run_dir), other]) is other


def test_resume_continues_the_same_session_and_is_not_a_new_try(setup):
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    assert ops_runs.resume(run_dir.name)["status"] == "running"
    assert Runner(adapters, lib).drive(run_dir) == "done"
    first, second = [c[2] for c in adapters.claude.calls if c[0] == "launch"]
    assert "resume_session" not in first and second["resume_session"] == SESSION
    text = Path(second["prompt_file"]).read_text()
    assert text.splitlines()[0] == "You were paused mid-step. Check the files you were changing, then carry on."
    assert "Review Task 1" in text
    st = state.load(run_dir)
    assert st["tasks"]["1"]["tries"] == 1
    assert reviewer_line(run_dir)["status"] == "passed" and (paths.work("proj", run_dir.name) / "wip.txt").exists()


def test_missing_session_file_restarts_clean_and_says_so(setup):
    run_dir, adapters, lib = setup
    adapters.claude = PausingClaude(lambda: run_dir.name, keep_session_file=False)
    Runner(adapters, lib).drive(run_dir)
    ops_runs.resume(run_dir.name)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    second = [c[2] for c in adapters.claude.calls if c[0] == "launch"][1]
    assert "resume_session" not in second
    assert not Path(second["prompt_file"]).read_text().startswith("You were paused")
    assert not (paths.work("proj", run_dir.name) / "wip.txt").exists()      # back to the attempt's base
    assert "Restarted clean" in reviewer_line(run_dir)["note"]
    assert state.load(run_dir)["tasks"]["1"]["tries"] == 1


@pytest.mark.parametrize("bad", ["sess-1", "../../etc/x", "--help"])
def test_a_session_id_that_is_not_a_uuid_restarts_clean(setup, bad):
    run_dir, adapters, lib = setup
    adapters.claude = PausingClaude(lambda: run_dir.name, session_id=bad, keep_session_file=False)
    Runner(adapters, lib).drive(run_dir)
    ops_runs.resume(run_dir.name)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    second = [c[2] for c in adapters.claude.calls if c[0] == "launch"][1]
    assert "resume_session" not in second
    assert "Restarted clean" in reviewer_line(run_dir)["note"]


def test_a_failed_resume_session_still_counts_its_cost(setup):
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    before = state.load(run_dir)["usage"]["sessions"]
    real = adapters.claude.launch

    def launch(docker_, **kw):
        if kw.get("resume_session"):
            adapters.claude.calls.append(("launch", (), kw))
            return Result(kind="error", text="No conversation found", cost_usd=0.4)
        return real(docker_, **kw)
    adapters.claude.launch = launch
    ops_runs.resume(run_dir.name)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    usage = state.load(run_dir)["usage"]
    assert usage["sessions"] == before + 2 and usage["cost_usd"] >= 0.4


def test_failed_resume_restarts_clean(setup):
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    adapters.claude.scripts[("reviewer", None, None)] = [{"kind": "error"}]
    real = adapters.claude.launch

    def launch(docker_, **kw):
        if kw.get("resume_session"):
            adapters.claude.calls.append(("launch", (), kw))
            return Result(kind="error", text="No conversation found")
        return real(docker_, **kw)
    adapters.claude.launch = launch
    adapters.claude.scripts.clear()
    ops_runs.resume(run_dir.name)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    assert "Restarted clean" in reviewer_line(run_dir)["note"]
    assert not (paths.work("proj", run_dir.name) / "wip.txt").exists()


def test_resume_waits_in_the_queue_when_another_run_is_going(setup, tmp_path):
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    other = make_run(tmp_path, spec=ONE_TASK)
    state.set_status(other, "running")
    assert ops_runs.resume(run_dir.name) == {"run_id": run_dir.name, "status": "queued", "queued": True}


def test_pause_during_a_script_step_waits_for_it_to_end(setup):
    run_dir, adapters, lib = setup
    adapters.claude.pause_first = False
    state.update(run_dir, lambda s: s.update(status="running", current={"group": "task", "task": 1, "step": "builder",
                                                                       "attempt": 1, "gate": None}))
    reply = ops_runs.pause(run_dir.name, now=True)
    assert reply["waits_for_step"] and "not an AI step" in reply["notes"][0]
    assert adapters.docker.stopped == []
    assert Runner(adapters, lib).drive(run_dir) == "paused"
    assert order(run_dir) == []              # nothing ran: it paused at the step boundary


def test_pause_and_resume_refuse_the_wrong_state(setup):
    run_dir, adapters, lib = setup
    with pytest.raises(OpsError, match="not paused"):
        ops_runs.resume(run_dir.name)
    with pytest.raises(OpsError, match="no running step"):
        ops_runs.pause(run_dir.name, now=True)
    with pytest.raises(OpsError, match="--now"):
        ops_runs.pause(run_dir.name)


def test_stopping_a_paused_run_works(setup):
    run_dir, adapters, lib = setup
    Runner(adapters, lib).drive(run_dir)
    assert ops_runs.stop(run_dir.name)["status"] == "stopped"


def test_state_accepts_paused():
    assert "paused" in state.RUN_STATUSES and "paused" in state.STEP_STATUSES


def test_claude_folder_is_the_attempt_folder_and_mounted_as_projects(tmp_path):
    here = docker.transcript_dir("proj", "r1", 2, 3, "builder")
    assert here == paths.runs("proj") / "r1" / "tasks" / "2" / "attempt-3" / "claude" / "builder"
    prompt = tmp_path / "p.md"
    prompt.write_text("x")
    paths.secrets().mkdir(parents=True)
    (paths.secrets() / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=x\n")
    r = docker.claude_run("proj", "r1", 2, 3, "builder", "img", tmp_path, prompt, ["claude"])
    (m,) = [m for m in r.mounts if m.dst == "/home/node/.claude/projects"]
    assert Path(m.src) == here and not m.ro


def test_resume_goes_on_the_claude_command_line():
    cmd = build_command({"model": "m"}, "/p", "/workspace", resume=SESSION)
    assert cmd[cmd.index("--resume") + 1] == SESSION and "--bare" not in cmd
    assert "--resume" not in build_command({"model": "m"}, "/p", "/workspace")


def test_session_id_is_read_from_the_log_when_the_session_never_finished(tmp_path):
    from phoenix9 import claude
    log = tmp_path / "x.jsonl"
    log.write_text('{"type":"system","subtype":"init","session_id":"s-9"}\n{"type":"assista')
    assert claude.session_id_in_log(log) == "s-9"
    assert claude.session_id_in_log(tmp_path / "none.jsonl") == ""


def _last_json(text):
    return text[text.index("{"):]


def test_cli_pause_needs_yes_and_resume_works(setup, capsys):
    run_dir, adapters, lib = setup
    assert main(["run", "pause", run_dir.name, "--now"]) != 0
    Runner(adapters, lib).drive(run_dir)
    assert main(["run", "resume", run_dir.name, "--json"]) == 0
    assert json.loads(_last_json(capsys.readouterr().out))["status"] == "running"
