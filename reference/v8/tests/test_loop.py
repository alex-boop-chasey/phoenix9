"""Tests for phoenix/loop.py. A local bare repo stands in for GitHub; the check writer,
red check, builder container, verify and the clock are fakes. Git and run.json are real."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phoenix import __main__ as cli
from phoenix import checks, claude, config, docker, loop, runs
from phoenix import git as pgit
from phoenix.verify import Verdict

REPO = "alex-boop-chasey/loop-site"
RUN = "20261030-1405-loop"

PLAN = """# Plan: Loop site

Type: change
Repo: alex-boop-chasey/loop-site

## About
A tiny site used to test the Phoenix loop.

## Every step
Keep it simple.

## Step 1: Home page
Add a home page.

Done when:
- The home page shows the text "Welcome"

## Step 2: Menu page
{step2_extra}Add a menu page.

Done when:
- The menu page lists three kinds of bread

## Step 3: Order page
{step3_extra}Add an order page.

Done when:
- The order page has a form with a name field
"""


def sh(cwd, *args):
    """Run a plain git command in a test folder and return its output."""
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def make_run(tmp_path, monkeypatch, step2_extra="", step3_extra=""):
    """Create origin, the plan file and a queued run.json for RUN."""
    base, seed = tmp_path / "remotes", tmp_path / "seed"
    seed.mkdir()
    sh(seed, "init", "-q", "-b", "main")
    (seed / "README.md").write_text("loop site\n")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "init")
    base.mkdir()
    sh(tmp_path, "clone", "-q", "--bare", str(seed), str(base / "loop-site.git"))
    monkeypatch.setenv("PHOENIX_GIT_BASE", str(base))
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN.format(step2_extra=step2_extra, step3_extra=step3_extra))
    record = runs.load_run(RUN)
    record.update(repo=REPO, plan_path=str(plan_file))
    runs.save_run(record)
    return plan_file


@pytest.fixture
def plan_file(tmp_path, monkeypatch):
    """The 3-step plan, every step depending on the one before."""
    return make_run(tmp_path, monkeypatch)


class Fakes:
    """Fake outside pieces for the loop, recording every call.

    `results[step]` is a list of builder results, one per call (the last one repeats);
    `passes` = the steps whose checks pass; `crash_builder` / `crash_verify` = step
    numbers whose first builder or verify call raises (the loop being killed).
    """

    def __init__(self, passes=(1, 2, 3), results=None, crash_builder=(), crash_verify=()):
        self.passes = set(passes)
        self.results = results or {}
        self.crash_builder, self.crash_verify = set(crash_builder), set(crash_verify)
        self.written, self.builder_calls, self.verify_calls, self.orphans = [], [], [], []
        self.sleeps, self.clock = [], datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)

    def write_checks(self, run, step, settings=None):
        self.written.append(step.number)
        clone = pgit.clone_dir(run["repo"])
        rel = f"{checks.step_folder(step.number)}/1-check.test.ts"
        (clone / rel).parent.mkdir(parents=True, exist_ok=True)
        (clone / rel).write_text(f"// check for step {step.number}\n")
        pgit.git(clone, "add", "--", rel)
        pgit.git(clone, *pgit.IDENT, "commit", "-q", "-m", f"Step {step.number}: checks")
        return [Path(rel)]

    def red_check(self, run, step, settings=None):
        checks.note_step(run["run_id"], step.number, red_check="failing")
        return True

    def builder(self, run_id, step, try_no, role, workspace, prompt_file, env_files, domains, timeout, **kw):
        n = len([c for c in self.builder_calls if c["step"] == step])
        self.builder_calls.append({"step": step, "try": try_no, "role": role, "timeout": timeout,
                                   "prompt": Path(prompt_file).read_text(),
                                   "system": Path(kw["system_prompt_file"]).read_text(), **kw})
        if step in self.crash_builder:
            self.crash_builder.discard(step)
            raise RuntimeError("the loop was killed")
        (Path(workspace) / "src").mkdir(exist_ok=True)
        (Path(workspace) / "src" / f"step-{step}.txt").write_text(f"try {try_no}\n")
        plan = self.results.get(step, [claude.Result(kind="ok", text="All done.\nSTEP DONE")])
        return plan[min(n, len(plan) - 1)]

    def verify(self, run, step, sha, try_no=1, settings=None):
        self.verify_calls.append({"step": step.number, "sha": sha, "try": try_no})
        if step.number in self.crash_verify:
            self.crash_verify.discard(step.number)
            raise RuntimeError("the loop was killed")
        if step.number in self.passes:
            return Verdict(passed=1, ok=True, reason="all 1 passed")
        return Verdict(failed=1, reason="1 failed: menu lists bread")

    def cleanup_orphans(self, run_id=None):
        self.orphans.append(run_id)
        return 0

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock += timedelta(seconds=seconds)

    def tools(self, probe=None):
        return loop.Tools(write_checks=self.write_checks, red_check=self.red_check, builder=self.builder,
                          verify=self.verify, cleanup_orphans=self.cleanup_orphans, now=self.now,
                          sleep=self.sleep, probe=probe)

    def tries(self, step):
        return [c["try"] for c in self.builder_calls if c["step"] == step]


def statuses():
    """Return {step number: status} from run.json."""
    return {e["number"]: e["status"] for e in runs.load_run(RUN)["steps"]}


def entry(n):
    """Return step n's entry in run.json."""
    return loop.step_entry(runs.load_run(RUN), n)


def branch_log(fmt="%s"):
    """Return the run branch's commits after base, newest first."""
    base = runs.load_run(RUN)["base_sha"]
    return pgit.git(pgit.clone_dir(REPO), "log", f"--format={fmt}", f"{base}..HEAD").splitlines()


# ------------------------------------------------------------- tries, failure and dependents
def test_step_2_fails_three_times_then_step_3_is_blocked(plan_file):
    f = Fakes(passes=(1, 3))
    assert loop.run_plan(RUN, tools=f.tools()) == "failed"
    assert statuses() == {1: "passed", 2: "failed", 3: "blocked"}
    assert f.tries(2) == [1, 2, 3]                       # 3 builder calls for step 2
    assert f.tries(3) == []                              # step 3 never started
    assert f.written == [1, 2]                           # checks written once per step, not per try
    assert entry(2)["tries"] == 3
    assert entry(2)["reason"].startswith("The checks did not pass: 1 failed: menu lists bread")
    assert entry(3)["reason"] == "step 2 failed"
    assert pgit.passed_steps(REPO, runs.load_run(RUN)["base_sha"]) == [1]
    # every failed candidate commit was thrown away: the branch ends with step 2's lock commit
    assert branch_log()[:3] == ["Step 2: lock checks", "Step 2: checks", "Step 1: Home page"]
    record = runs.load_run(RUN)
    assert record["status"] == "failed" and record["current_step"] is None


def test_builder_gets_feedback_on_later_tries_and_the_check_command(plan_file):
    f = Fakes(passes=(1, 3))
    loop.run_plan(RUN, tools=f.tools())
    calls = [c for c in f.builder_calls if c["step"] == 2]
    assert "None: this is try 1 of 3." in calls[0]["system"]
    assert "This is try 2 of 3" in calls[1]["system"]
    assert "The checks did not pass: 1 failed: menu lists bread" in calls[1]["system"]
    assert "npx vitest run tests/phoenix/step-02" in calls[0]["system"]
    assert "Step 1: Home page" in calls[0]["system"]                 # git log of the run so far
    assert "Add a menu page." in calls[0]["system"] and "1. The menu page lists three kinds" in calls[0]["system"]
    assert "STEP DONE" in calls[0]["prompt"]
    assert calls[0]["max_turns"] == 200 and calls[0]["role"] == "builder"
    assert calls[0]["timeout"] == 90 and calls[0]["no_output_timeout_min"] == 15
    assert any(m.dst == "/phoenix/testconfig" for m in calls[0]["mounts"])
    saved = runs.run_dir(RUN) / "prompts" / "2-1-feedback.md"
    assert saved.read_text().startswith("The checks did not pass")


def test_early_session_end_counts_as_a_failed_try_without_verify(plan_file):
    f = Fakes(results={1: [claude.Result(kind="timed_out", text="stopped")]})
    assert loop.run_plan(RUN, tools=f.tools()) == "failed"
    assert f.tries(1) == [1, 2, 3]
    assert f.verify_calls == []
    assert statuses() == {1: "failed", 2: "blocked", 3: "blocked"}
    assert "timed_out" in entry(1)["reason"]


def test_snapshot_rejection_counts_as_a_failed_try(plan_file):
    f = Fakes()
    real_builder = f.builder

    def tamper(run_id, step, try_no, role, workspace, *a, **kw):
        result = real_builder(run_id, step, try_no, role, workspace, *a, **kw)
        if step == 1 and try_no == 1:
            (Path(workspace) / "tests/phoenix/step-01/1-check.test.ts").write_text("// weakened\n")
        return result

    tools = f.tools()
    tools.builder = tamper
    assert loop.run_plan(RUN, tools=tools) == "done"
    assert f.tries(1) == [1, 2]
    assert [c["try"] for c in f.verify_calls if c["step"] == 1] == [2]
    feedback = (runs.run_dir(RUN) / "prompts" / "1-1-feedback.md").read_text()
    assert "Phoenix refused" in feedback and "1-check.test.ts" in feedback
    run_log = (runs.run_dir(RUN) / "logs" / "phoenix.log").read_text()
    assert "step 1: Phoenix refused the changes of try 1: " in run_log and "1-check.test.ts" in run_log


# ------------------------------------------------------------- For you, rate limits
def test_for_you_step_is_skipped_and_listed(tmp_path, monkeypatch, capsys):
    make_run(tmp_path, monkeypatch, step2_extra="For you: yes\n", step3_extra="Depends on: 1\n")
    f = Fakes()
    assert loop.run_plan(RUN, tools=f.tools()) == "done"
    assert statuses() == {1: "passed", 2: "for_you", 3: "passed"}
    assert f.tries(2) == [] and f.written == [1, 3]
    assert cli.main(["status", RUN]) == 0
    out = capsys.readouterr().out
    assert " 2  Menu page  for_you  tries 0  For you: the owner does this step by hand" in out
    assert " 1  Home page  passed  tries 1" in out


def test_step_depending_on_a_for_you_step_is_blocked(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch, step2_extra="For you: yes\n")
    f = Fakes()
    assert loop.run_plan(RUN, tools=f.tools()) == "failed"
    assert statuses() == {1: "passed", 2: "for_you", 3: "blocked"}
    assert entry(3)["reason"] == "depends on step 2, which did not pass"


def test_rate_limit_waits_on_the_fake_clock_and_does_not_use_a_try(plan_file):
    f = Fakes()
    limited = claude.Result(kind="rate_limited", text="You've hit your limit · resets 10:30am",
                            resets_at=f.clock + timedelta(minutes=30))
    f.results = {1: [limited, claude.Result(kind="ok", text="STEP DONE")]}
    assert loop.run_plan(RUN, tools=f.tools()) == "done"
    assert f.tries(1) == [1, 1]                          # the same try, repeated
    assert entry(1)["tries"] == 1
    assert f.sleeps == [32 * 60]                          # until the reset, plus 2 minutes
    assert statuses() == {1: "passed", 2: "passed", 3: "passed"}


def test_rate_limit_that_never_lifts_pauses_the_run(plan_file):
    f = Fakes(results={1: [claude.Result(kind="rate_limited", text="You've hit your limit")]})
    probes = []

    def probe():
        probes.append(f.clock)
        return claude.Result(kind="rate_limited", text="still limited")

    assert loop.run_plan(RUN, tools=f.tools(probe=probe)) == "paused"
    assert len(probes) >= 1 and f.tries(1) == [1]
    assert runs.load_run(RUN)["status"] == "paused"
    assert sum(f.sleeps) == 12 * 3600                     # usage_max_wait_h, then gave up


# ------------------------------------------------------------- resume after a restart
def test_killed_after_step_1_resumes_at_step_2_with_passes_from_git(plan_file):
    first = Fakes(crash_builder=(2,))
    with pytest.raises(RuntimeError, match="killed"):
        loop.run_plan(RUN, tools=first.tools())
    record = runs.load_run(RUN)
    assert record["status"] == "running" and record["current_step"] == 2
    # run.json loses step 1's pass (git must win); a workspace was left behind
    for e in record["steps"]:
        e.update(status="pending", tries=0)
    runs.save_run(record)
    leftover = pgit.work_root() / f"{RUN}-2-1"
    leftover.mkdir(parents=True, exist_ok=True)

    second = Fakes()
    assert loop.run_plan(RUN, tools=second.tools()) == "done"
    assert second.orphans == [RUN]                        # leftover containers removed
    assert not leftover.exists()
    assert second.tries(1) == []                          # step 1 not built again: git says it passed
    assert second.builder_calls[0]["step"] == 2 and second.tries(2) == [1]
    assert second.written == [3]                          # step 2's checks were already written and locked
    assert statuses() == {1: "passed", 2: "passed", 3: "passed"}
    assert pgit.passed_steps(REPO, runs.load_run(RUN)["base_sha"]) == [1, 2, 3]


def test_candidate_commit_of_the_interrupted_step_is_reset(plan_file):
    first = Fakes(crash_verify=(2,))
    with pytest.raises(RuntimeError):
        loop.run_plan(RUN, tools=first.tools())
    trailers = branch_log("%(trailers:key=Phoenix-Step,valueonly)")
    assert trailers[0].strip() == "2"                     # the unjudged candidate is on the branch

    second = Fakes()
    assert loop.run_plan(RUN, tools=second.tools()) == "done"
    assert second.tries(2) == [1]
    steps = [t.strip() for t in branch_log("%(trailers:key=Phoenix-Step,valueonly)") if t.strip()]
    assert steps == ["3", "2", "1"]                       # one commit per step, the candidate is gone
    assert entry(2)["tries"] == 1


def test_run_json_saying_passed_without_a_git_trailer_is_redone(plan_file):
    f = Fakes()
    assert loop.run_plan(RUN, tools=f.tools()) == "done"
    clone = pgit.clone_dir(REPO)
    # drop step 3's commit from git, and pretend the loop was still running
    pgit.git(clone, "reset", "-q", "--hard", "HEAD~1")
    loop.note_run(RUN, status="running", current_step=None)
    again = Fakes()
    assert loop.run_plan(RUN, tools=again.tools()) == "done"
    assert again.tries(3) == [1] and again.tries(1) == again.tries(2) == []


def test_finished_run_is_not_run_again(plan_file):
    loop.run_plan(RUN, tools=Fakes().tools())
    again = Fakes()
    assert loop.run_plan(RUN, tools=again.tools()) == "done"
    assert again.builder_calls == []


# ------------------------------------------------------------- prompt, mounts, CLI
def test_builder_prompt_is_short_and_has_every_part():
    text = loop.PROMPT_TEMPLATE.read_text()
    assert len(text.splitlines()) < 80
    for key in ("about", "every_step", "step_title", "step_description", "done_when", "check_command",
                "git_log", "feedback"):
        assert "{{" + key + "}}" in text
    assert "STEP DONE" in text and "STEP BLOCKED: <reason>" in text and "tests/phoenix/" in text


def test_builder_container_passes_extra_mounts_and_appends_the_system_prompt(tmp_path):
    prompt, system = tmp_path / "p.md", tmp_path / "s.md"
    r = docker.claude_run(RUN, 1, 1, "builder", tmp_path, prompt, [], None, system_prompt_file=system,
                          mounts=[docker.Mount(tmp_path, "/out", ro=False)])
    assert "--append-system-prompt-file" in r.cmd and "--bare" not in r.cmd
    assert any(m.dst == "/out" for m in r.mounts)


def test_cli_run_and_status(plan_file, monkeypatch, capsys):
    f = Fakes(passes=(1, 3))
    real_run_plan = loop.run_plan
    monkeypatch.setattr(loop, "run_plan", lambda run_id: real_run_plan(run_id, tools=f.tools()))
    assert cli.main(["run", RUN]) == 1
    out = capsys.readouterr().out
    assert f"run {RUN}: failed" in out
    assert cli.main(["status", RUN]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"run {RUN}: failed"
    assert lines[2].startswith(" 2  Menu page  failed  tries 3  The checks did not pass")
    assert lines[3] == " 3  Order page  blocked  tries 0  step 2 failed"


def test_cli_unknown_run(capsys):
    assert cli.main(["status", "nope"]) == 1
    assert "No run called nope" in capsys.readouterr().out
