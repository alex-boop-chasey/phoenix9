"""Tests for phoenix/run.py. A local bare repo stands in for GitHub; the full-suite container,
gh and notify are fakes. Git (including the push to the bare repo) and run.json are real."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from phoenix import config, runs
from phoenix import git as pgit
from phoenix import run as prun

REPO = "alex-boop-chasey/run-site"
RUN = "20261030-1405-runa"
PR_URL = "https://github.com/alex-boop-chasey/run-site/pull/7"

PLAN = """# Plan: Bakery site

Type: {type}
Repo: alex-boop-chasey/run-site

## About
A small bakery site used to test starting and finishing runs.

## Step 1: Home page
Add a home page.

Done when:
- The home page shows the text "Welcome"

## Step 2: Connect the shop's Stripe account
For you: yes
Log in to Stripe and paste the test key into the project env file.

Done when:
- The project env file has a STRIPE_SECRET_KEY line
"""


def sh(cwd, *args):
    """Run a plain git command in a test folder and return its output."""
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def make_run(tmp_path, monkeypatch, plan_type="change", scripts=None):
    """Create origin (with a package.json), the plan file and a queued run.json for RUN."""
    base, seed = tmp_path / "remotes", tmp_path / "seed"
    seed.mkdir()
    sh(seed, "init", "-q", "-b", "main")
    pkg = {"name": "run-site", "scripts": scripts if scripts is not None else {"test": "vitest run"}}
    (seed / "package.json").write_text(json.dumps(pkg))
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "init")
    base.mkdir()
    sh(tmp_path, "clone", "-q", "--bare", str(seed), str(base / "run-site.git"))
    monkeypatch.setenv("PHOENIX_GIT_BASE", str(base))
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN.format(type=plan_type))
    record = runs.load_run(RUN)
    record.update(repo=REPO, plan_path=str(plan_file), plan_name="Bakery site")
    runs.save_run(record)
    return base / "run-site.git"


class Fakes:
    """Fake suite container, gh and notify, recording every call.

    `suite` = list of exit codes, one per container call (the last one repeats).
    A red run writes a Vitest FAIL line to the suite output.
    """

    def __init__(self, suite=(0,), pr_state="OPEN"):
        self.suite = list(suite)
        self.pr_state = pr_state
        self.container_calls, self.gh_calls, self.notes = [], [], []

    def container(self, run_id, step, try_no, checkout, command, env_file, domains, timeout, **kw):
        n = len(self.container_calls)
        self.container_calls.append({"label": step, "try": try_no, "command": command, "role": kw["role"],
                                     "package": json.loads((Path(checkout) / "package.json").read_text())})
        rc = self.suite[min(n, len(self.suite) - 1)]
        out_dir = Path(kw["mounts"][0].src)
        if rc:
            (out_dir / prun.SUITE_FILE).write_text(" FAIL  tests/price.test.ts > prices add up\n")
        (out_dir / "test-results").mkdir(exist_ok=True)
        (out_dir / "test-results" / "home.png").write_bytes(b"\x89PNG fake")
        log = config.paths().runs / run_id / "logs" / f"{step}-{try_no}-suite.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("suite output\n")
        return rc, log

    def gh(self, args):
        self.gh_calls.append(args)
        if args[:2] == ["pr", "create"]:
            return subprocess.CompletedProcess(args, 0, f"Creating pull request...\n{PR_URL}\n", "")
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"state": self.pr_state}), "")
        return subprocess.CompletedProcess(args, 1, "", "unknown")

    def notify(self, text):
        self.notes.append(text)

    def hands(self, push=None):
        return prun.Hands(container=self.container, gh=self.gh, notify=self.notify,
                          **({"push": push} if push else {}))


def after_loop(status="done"):
    """Make run.json look like the step loop just ended: step 1 passed, step 2 for you."""
    record = runs.load_run(RUN)
    record.update(status=status, cost_usd=1.25, steps=[
        {"number": 1, "title": "Home page", "status": "passed", "tries": 2, "reason": ""},
        {"number": 2, "title": "Connect the shop's Stripe account", "status": "for_you", "tries": 0,
         "reason": "For you: the owner does this step by hand"}])
    runs.save_run(record)
    usage = runs.run_dir(RUN) / "usage.jsonl"
    usage.write_text('{"kind": "ok"}\n{"kind": "ok"}\n{"kind": "ok"}\n')


# ------------------------------------------------------------- start_run
def test_start_run_on_a_green_main(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[0])
    assert prun.start_run(RUN, hands=f.hands()) == "ready"
    record = runs.load_run(RUN)
    assert record["status"] == "queued"                       # run_plan sets `running`
    assert record["branch"] == "phoenix/" + RUN and record["base_sha"]
    assert record["full_suite"] == {"start": "green", "start_test": "", "command": "pnpm test"}
    plan = json.loads((runs.run_dir(RUN) / "2-plan" / "plan.json").read_text())
    assert plan["name"] == "Bakery site" and len(plan["steps"]) == 2
    assert (config.paths().config / "projects" / "run-site.domains").read_text().startswith("api.anthropic.com")
    clone = pgit.clone_dir(REPO)
    assert pgit.git(clone, "log", "-1", "--format=%s").strip() == f"Phoenix run {RUN}: plan"
    call = f.container_calls[0]
    assert (call["label"], call["try"], call["role"]) == ("start", 1, "suite")
    assert "pnpm install --frozen-lockfile" in call["command"] and "( pnpm test )" in call["command"]
    assert prun.start_run(RUN, hands=f.hands()) == "ready"    # safe to call again: no second plan commit
    assert pgit.git(clone, "rev-list", "--count", "HEAD").strip() == "2"


def test_red_main_fails_the_run_with_the_test_name(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[1])
    assert prun.start_run(RUN, hands=f.hands()) == "failed"
    record = runs.load_run(RUN)
    assert record["status"] == "failed"
    assert record["reason"] == "main is already red: tests/price.test.ts > prices add up"
    assert record["finished_at"]
    assert f.notes and "main is already red" in f.notes[0]
    assert "red: tests/price.test.ts > prices add up" in (runs.run_dir(RUN) / "summary.md").read_text()


def test_new_project_skips_the_suite_at_the_start(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch, plan_type="new")
    f = Fakes(suite=[1])
    assert prun.start_run(RUN, hands=f.hands()) == "ready"
    assert f.container_calls == []
    assert runs.load_run(RUN)["full_suite"]["start"] == "skipped"


def test_suite_command_without_package_json():
    assert prun.suite_command(Path("/nowhere")) is None


@pytest.mark.parametrize("scripts, expected", [
    ({"test": "vitest run", "test:all": "vitest run && playwright test"}, "pnpm run test:all"),
    ({"test": "vitest run"}, "pnpm test"),
    ({"test": 'echo "Error: no test specified" && exit 1'}, None),
    ({"build": "next build"}, None),
])
def test_suite_command(tmp_path, scripts, expected):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))
    assert prun.suite_command(tmp_path) == expected


def test_no_test_script_counts_as_no_suite(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch, scripts={})
    f = Fakes()
    assert prun.start_run(RUN, hands=f.hands()) == "ready"
    assert f.container_calls == [] and runs.load_run(RUN)["full_suite"]["start"] == "none"


# ------------------------------------------------------------- finish_run
def test_finish_run_with_a_red_suite_reruns_once_records_red_and_still_opens_the_pr(tmp_path, monkeypatch):
    bare = make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[0, 1, 1])                                 # green on main, red twice at the end
    prun.start_run(RUN, hands=f.hands())
    after_loop()
    assert prun.finish_run(RUN, hands=f.hands()) == "done"
    ends = [(c["label"], c["try"]) for c in f.container_calls[1:]]
    assert ends == [("end", 1), ("end", 2)]
    record = runs.load_run(RUN)
    assert record["status"] == "done"
    assert record["full_suite"]["end"] == "red"
    assert record["full_suite"]["end_test"] == "tests/price.test.ts > prices add up"
    assert record["full_suite"]["end_tries"] == 2
    assert record["pr_url"] == PR_URL and record["finished_at"]
    create = next(a for a in f.gh_calls if a[:2] == ["pr", "create"])
    assert create[create.index("--title") + 1] == f"Phoenix run {RUN}: Bakery site"
    assert create[create.index("--head") + 1] == f"phoenix/{RUN}"
    assert create[create.index("--base") + 1] == "main"
    body = Path(create[create.index("--body-file") + 1]).read_text()
    assert "Things only you can do" in body and "prices add up" in body
    sha = pgit.head(pgit.clone_dir(REPO))
    assert sh(bare, "rev-parse", f"refs/heads/phoenix/{RUN}").strip() == sha     # really pushed
    assert sh(bare, "rev-parse", "refs/heads/main").strip() != sha                # main untouched
    product = runs.run_dir(RUN) / "3-product"
    assert (product / "final-commit.txt").read_text() == sha + "\n"
    assert record["final_commit"] == sha
    assert sorted(p.name for p in (product / "screenshots").iterdir()) == [
        "suite-end-1--test-results--home.png", "suite-end-2--test-results--home.png",
        "suite-start-1--test-results--home.png"]
    summary = (runs.run_dir(RUN) / "summary.md").read_text()
    assert PR_URL in summary and "still red after 2 runs" in summary
    assert f.notes[-1].startswith(f"Phoenix run {RUN} done: 1 of 2 steps passed; full suite red")


def test_finish_run_green_runs_the_suite_once(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[0])
    prun.start_run(RUN, hands=f.hands())
    after_loop()
    prun.finish_run(RUN, hands=f.hands())
    assert len(f.container_calls) == 2
    suite = runs.load_run(RUN)["full_suite"]
    assert (suite["start"], suite["end"], suite["end_tries"]) == ("green", "green", 1)


def test_finish_run_keeps_a_failed_status_and_reports_a_push_problem(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[0])
    prun.start_run(RUN, hands=f.hands())
    after_loop(status="failed")

    def bad_push(repo, run_id):
        raise pgit.GitError("network is down")

    assert prun.finish_run(RUN, hands=f.hands(push=bad_push)) == "failed"
    record = runs.load_run(RUN)
    assert record["reason"] == "could not push the branch: network is down"
    assert record["pr_url"] == "" and not any(a[:2] == ["pr", "create"] for a in f.gh_calls)
    assert "failed" in f.notes[-1] and "network is down" in f.notes[-1]


# ------------------------------------------------------------- the summary
def test_summary_lists_a_for_you_step_under_things_only_you_can_do(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    after_loop()
    record = runs.load_run(RUN)
    record.update(pr_url=PR_URL, branch=f"phoenix/{RUN}",
                  full_suite={"start": "green", "end": "red", "end_test": "x > y", "end_tries": 2})
    runs.save_run(record)
    prun.write_summary(record)
    text = (runs.run_dir(RUN) / "summary.md").read_text()
    head, _, you = text.partition("## Things only you can do")
    assert "- Step 2: Connect the shop's Stripe account" in you
    assert "Log in to Stripe and paste the test key" in you
    assert "Step 1: Home page — passed, 2 tries" in head
    assert "Step 2: Connect the shop's Stripe account — for_you, 0 tries" in head
    assert "- Repo: alex-boop-chasey/run-site" in head and f"- Pull request: {PR_URL}" in head
    assert "- Full suite at the start: green" in head and "- Full suite at the end: red: x > y" in head
    assert "- Cost: $1.25 in 3 Claude session(s)" in head
    page = (runs.run_dir(RUN) / "summary.html").read_text()
    assert "<script" not in page.lower() and "{{" not in page
    assert "Connect the shop&#x27;s Stripe account" in page and f'<a href="{PR_URL}">' in page
    assert len(prun.HTML_TEMPLATE.read_text().splitlines()) <= 110


def test_summary_without_for_you_steps_says_nothing(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    record = runs.load_run(RUN)
    text = prun.summary_markdown(record, None)
    assert text.rstrip().endswith("## Things only you can do\n\nNothing.")


# ------------------------------------------------------------- notify
def test_notify_runs_the_telegram_script_with_the_text(tmp_path):
    out = tmp_path / "sent.txt"
    script = tmp_path / "ph-notify"
    script.write_text(f'#!/bin/sh\nprintf "%s" "$1" > {out}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    prun.notify("Run x done: it's ready", {"telegram_script": str(script)})
    assert out.read_text() == "Run x done: it's ready"


def test_notify_prints_without_a_script_and_never_raises(capsys, tmp_path):
    prun.notify("hello", {"telegram_script": ""})
    prun.notify("still fine", {"telegram_script": str(tmp_path / "missing")})
    out = capsys.readouterr().out
    assert "NOTIFY: hello" in out and "NOTIFY FAILED" in out


# ------------------------------------------------------------- merge detection
def finished_run(tmp_path, monkeypatch, pr_state="OPEN"):
    bare = make_run(tmp_path, monkeypatch)
    f = Fakes(suite=[0], pr_state=pr_state)
    prun.start_run(RUN, hands=f.hands())
    after_loop()
    prun.finish_run(RUN, hands=f.hands())
    return bare, f


def test_merged_branch_marks_the_run_merged(tmp_path, monkeypatch):
    bare, f = finished_run(tmp_path, monkeypatch)
    work = tmp_path / "owner"
    sh(tmp_path, "clone", "-q", str(bare), str(work))
    sh(work, "merge", "-q", "--no-ff", "-m", "merge", f"origin/phoenix/{RUN}")
    sh(work, "push", "-q", "origin", "main")
    assert prun.check_merged(RUN, hands=f.hands()) == "merged"
    assert runs.load_run(RUN)["status"] == "merged"


def test_squash_merged_pr_found_through_gh(tmp_path, monkeypatch):
    _, f = finished_run(tmp_path, monkeypatch, pr_state="MERGED")
    assert prun.check_merged(RUN, hands=f.hands()) == "merged"


def test_closed_pr_marks_the_run_abandoned_and_open_changes_nothing(tmp_path, monkeypatch):
    _, f = finished_run(tmp_path, monkeypatch, pr_state="OPEN")
    before = runs.load_run(RUN)
    assert prun.check_merged(RUN, hands=f.hands()) == "done"
    f.pr_state = "CLOSED"
    assert prun.check_merged(RUN, hands=f.hands()) == "abandoned"
    after = runs.load_run(RUN)
    assert after["status"] == "abandoned"
    assert {k: v for k, v in after.items() if k not in ("status", "updated_at")} == \
        {k: v for k, v in before.items() if k not in ("status", "updated_at")}


def test_gh_gets_the_token_from_github_env(monkeypatch, tmp_path):
    (config.paths().config).mkdir(parents=True, exist_ok=True)
    (config.paths().config / "github.env").write_text("GH_TOKEN=ghp_test_token_123\n")
    seen = {}

    def fake_run(argv, env, **kw):
        seen.update(argv=argv, token=env.get("GH_TOKEN"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setenv("GH_TOKEN", "from-the-shell")
    monkeypatch.setattr(prun.subprocess, "run", fake_run)
    prun.default_gh(["pr", "view", "1"])
    assert seen == {"argv": ["gh", "pr", "view", "1"], "token": "ghp_test_token_123"}


def test_a_missing_repo_fails_the_start_in_plain_words(tmp_path, monkeypatch):
    make_run(tmp_path, monkeypatch)
    monkeypatch.setenv("PHOENIX_GIT_BASE", str(tmp_path / "nowhere"))
    f = Fakes()
    assert prun.start_run(RUN, hands=f.hands()) == "failed"
    reason = runs.load_run(RUN)["reason"]
    assert reason.startswith("could not get the repo ready: fatal: ") and "credential" not in reason
