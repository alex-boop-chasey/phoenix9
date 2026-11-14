"""Full fake runs end to end: project new, then run start through the CLI, driven by the runner loop."""
import io
import json
import subprocess
from pathlib import Path

import pytest

from fakes import RealCheckDocker, fake_adapters
from phoenix9 import adapters as adapters_mod, paths, state, watch
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.runner import Runner

ROOT = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/alex/e2e.git"
PR_URL = "https://github.com/alex/e2e/pull/7"

SOURCES = {
    1: {"src/e2e/shout.py": 'def shout(text):\n    return text.upper() + "!"\n'},
    2: {"src/e2e/whisper.py": "def whisper(text):\n    return text.lower()\n"},
    3: {"src/e2e/loud.py": "from e2e import greet\nfrom e2e.shout import shout\n\n\n"
                           "def loud_greet(name):\n    return shout(greet(name))\n"},
}
TESTS = {
    1: ("test_shout.py", "from e2e.shout import shout\n\n\ndef test_shout():\n    assert shout('hi') == 'HI!'\n"),
    2: ("test_whisper.py", "from e2e.whisper import whisper\n\n\ndef test_whisper():\n    assert whisper('HI') == 'hi'\n"),
    3: ("test_loud.py", "from e2e.loud import loud_greet\n\n\ndef test_loud():\n    assert loud_greet('a') == 'HELLO, A!!'\n"),
}
BAD_TEST_1 = ("test_shout.py", "from e2e.shout import shout\n\n\ndef test_shout():\n    assert shout('hi') == 'nope'\n")
PASS = json.dumps({"verdict": "pass", "reasons": []})
DONE = "I wrote the code.\nSTEP DONE"
QUICK_LINES = (["pick-up", "spec-check", "branch", "service-setup"]
               + [s for _ in (1, 2, 3) for s in ("builder", "diff-rules", "secret-scan", "acceptance", "verify", "commit")]
               + ["lockfile", "full-suite", "summary", "preview", "merge", "deploy", "notify"])


class E2E:
    """Everything one end to end test needs: the fakes, the runner, and the CLI."""

    def __init__(self, adapters, runner):
        self.adapters, self.runner = adapters, runner
        self.claude, self.docker, self.host = adapters.claude, adapters.docker, adapters.host

    # ---- the CLI, in process
    def cli(self, *argv, stdin=None):
        """Run `phoenix <argv>` in process; return (exit code, printed text)."""
        import contextlib
        import sys
        out = io.StringIO()
        old_stdin = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out):
                rc = main(list(argv))
        finally:
            sys.stdin = old_stdin
        return rc, out.getvalue()

    def json(self, *argv, **kw):
        """Run a command with --json and return its parsed output (exit code must be 0)."""
        rc, text = self.cli(*argv, "--json", **kw)
        assert rc == 0, text
        return json.loads(text)

    # ---- the project and the run
    @property
    def code(self) -> Path:
        return paths.projects() / "e2e" / "code"

    def git(self, *args, cwd=None) -> str:
        """Run plain git in the project's code folder (or cwd) and return its output."""
        out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd or self.code,
                             capture_output=True, text=True, check=True)
        return out.stdout

    def start(self, spec="plans/e2e-quick.md", preset="quick") -> str:
        """Queue a run through the CLI and return its id."""
        spec_path = spec if Path(spec).is_absolute() else str(ROOT / spec)
        return self.json("run", "start", "e2e", "--spec", spec_path, "--preset", preset)["run_id"]

    def settle(self, rounds=60):
        """Drive the runner until it has nothing to do (finished, or waiting for an answer)."""
        for _ in range(rounds):
            if watch.watch_once(self.adapters, self.runner) is None:
                return
        raise AssertionError("the runner never settled")

    def state(self, run_id) -> dict:
        return state.load(paths.runs("e2e") / run_id)

    def run_dir(self, run_id) -> Path:
        return paths.runs("e2e") / run_id

    def open_gates(self) -> list:
        return self.json("gate", "list", "e2e")

    def answer(self, answer="approve", who=None, note=""):
        """Answer the one open gate through the CLI and return it."""
        found = self.open_gates()
        assert len(found) == 1, found
        argv = ["gate", "answer", found[0]["id"], answer]
        argv += ["--who", who] if who else []
        argv += ["--note", note] if note else []
        assert self.cli(*argv)[0] == 0
        return found[0]

    def steps(self, st, task=None) -> list:
        return [x["step"] for x in st["steps"] if task is None or x["task"] == task]

    def script_builders(self, failing=(), cost=0.5):
        """Script a Builder session per task that writes the source and test (the test is bad for `failing`)."""
        for n in (1, 2, 3):
            name, text = BAD_TEST_1 if n in failing else TESTS[n]
            self.claude.script("builder", n, files={**SOURCES[n], f"tests/{name}": text}, text=DONE, cost_usd=cost)


@pytest.fixture
def e2e(phoenix_env, tmp_path, monkeypatch):
    """Fake adapters (real check commands), PHOENIX_LIBRARY at the repo, and `phoenix project new e2e` done."""
    adapters = fake_adapters(tmp_path)
    adapters.docker = RealCheckDocker()
    claude_json = tmp_path / "claude.json"
    adapters.host.files[str(claude_json)] = json.dumps({"projects": {}})
    adapters.host.script(["gh", "pr", "create"], out=PR_URL + "\n")

    def never_real():
        raise AssertionError("the real adapters were constructed")

    monkeypatch.setattr(adapters_mod, "real", never_real)
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(ROOT))
    monkeypatch.setenv("PHOENIX_CLAUDE_JSON", str(claude_json))
    env = E2E(adapters, Runner(adapters, ROOT))
    rc, text = env.cli("project", "new", "e2e", "--profile", "python-script", "--template", "python-cli",
                       "--no-new-repo")
    assert rc == 0, text
    return env


def trailers(env, run_id) -> list[str]:
    """The Phoenix trailers of the run's commits (on main once merged; on the branch when the merge was left to GitHub), one string per commit."""
    branch = f"phoenix/{run_id}"
    here = env.git("branch", "--list", branch).strip()
    log = env.git("log", "--format=%B%x00", branch if here else "main").split("\0")
    return [c for c in log if "Phoenix-Run" in c]


def test_quick_run_done(e2e):
    e2e.script_builders()
    run_id = e2e.start()
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "done", st
    assert e2e.steps(st) == QUICK_LINES
    off = ("preview", "deploy")    # both skip themselves unless [deploy] says otherwise
    assert all(x["status"] == "passed" for x in st["steps"] if x["step"] not in off), [x for x in st["steps"] if x["status"] != "passed"]
    assert all(x["status"] == "skipped" for x in st["steps"] if x["step"] in off)
    commits = trailers(e2e, run_id)
    assert len(commits) == 3
    for n in (1, 2, 3):
        assert any(f"Phoenix-Task: {n}" in c and f"Phoenix-Run: {run_id}" in c and "Phoenix-Attempt: 1" in c
                   for c in commits)
    assert e2e.git("branch", "--list", f"phoenix/{run_id}").strip() == ""   # merged, so the branch is gone
    assert e2e.git("rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert all((e2e.code / f).exists() for f in ("src/e2e/shout.py", "src/e2e/whisper.py", "src/e2e/loud.py"))
    assert not any(c[0] in ("push",) for c in e2e.host.calls if c[:1] == ["git"])
    run_dir = e2e.run_dir(run_id)
    assert (run_dir / "summary.md").is_file() and (run_dir / "summary.html").is_file()
    assert "3 passed, 0 failed, 0 skipped" in e2e.cli("run", "log", run_id, "--summary")[1]
    assert len(e2e.adapters.notify.messages) == 1


def quick_spec_as_plan() -> str:
    """The Quick spec with Preset: full, as the Planner would write it."""
    return (ROOT / "plans" / "e2e-quick.md").read_text().replace("Preset: quick", "Preset: full")


def script_full(env, reviewer_fails=True):
    """Script a Full run: Planner, a Check-writer and Builder per task, and a Reviewer."""
    env.claude.script("planner", files={"/out/spec.md": quick_spec_as_plan()}, text="PLAN DONE", cost_usd=0.2)
    for n in (1, 2, 3):
        name, text = TESTS[n]
        env.claude.script("check-writer", n, files={f"tests/phoenix/{{run_id}}/task-{n}/{name}": text}, text="CHECKS DONE",
                          cost_usd=0.3)
        env.claude.script("builder", n, files=SOURCES[n], text=DONE, cost_usd=0.5)
        env.claude.script("reviewer", n, files={"/out/verdict.json": PASS}, text="REVIEWED", cost_usd=0.1)
    if reviewer_fails:
        bad = json.dumps({"verdict": "fail", "reasons": ["shout() must keep numbers in the text"]})
        env.claude.script("reviewer", 1, 1, files={"/out/verdict.json": bad}, text="REVIEWED", cost_usd=0.1)


def test_full_run_with_plan_gate_and_reviewer(e2e):
    script_full(e2e)
    e2e.git("remote", "add", "origin", GITHUB)
    assert e2e.cli("settings", "set", "e2e", "merge=ask")[0] == 0
    run_id = e2e.start("plans/e2e-full.md", "full")
    e2e.settle()
    gate = e2e.open_gates()[0]
    assert gate["kind"] == "plan" and e2e.state(run_id)["status"] == "waiting"
    e2e.answer("approve")
    e2e.settle()
    gate = e2e.open_gates()[0]
    assert gate["kind"] == "merge" and gate["flags"] == []
    assert {"label": "Merge request", "url": PR_URL} in gate["links"]
    e2e.answer("approve")
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "done", st
    task1 = [x for x in st["steps"] if x["task"] == 1]
    assert [x["step"] for x in task1].count("check-writer") == 1 and [x["step"] for x in task1].count("red-check") == 1
    assert [x["attempt"] for x in task1 if x["step"] in ("check-writer", "red-check")] == [1, 1]
    assert [x["step"] for x in task1].count("reviewer") == 2 and st["tasks"]["1"]["tries"] == 2
    prompt = (e2e.run_dir(run_id) / "tasks/1/attempt-2/builder-prompt.md").read_text()
    assert "shout() must keep numbers in the text" in prompt
    assert [st["tasks"][n]["status"] for n in "123"] == ["passed"] * 3
    assert len(trailers(e2e, run_id)) == 6    # a checks commit and a task commit per task
    assert ["gh", "pr", "merge", PR_URL, "--merge"] in e2e.host.calls


def set_settings(env, *assignments):
    """Change project settings through the CLI."""
    for a in assignments:
        assert env.cli("settings", "set", "e2e", a)[0] == 0


def fail_task_1_first(env, attempts=(1,)):
    """Builder scripts where task 1 writes a failing test on the given attempts and a good one after."""
    bad_name, bad_text = BAD_TEST_1
    good_name, good_text = TESTS[1]
    for k in attempts:
        env.claude.script("builder", 1, k, files={**SOURCES[1], f"tests/{bad_name}": bad_text}, text=DONE)
    env.claude.script("builder", 1, max(attempts) + 1, files={**SOURCES[1], f"tests/{good_name}": good_text},
                      text=DONE)
    for n in (2, 3):
        name, text = TESTS[n]
        env.claude.script("builder", n, files={**SOURCES[n], f"tests/{name}": text}, text=DONE)


def tell_questions_at_once():
    """Switch the quiet wait off, so a question's message goes out as soon as it opens."""
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text("[notify]\nquiet_minutes = 0\n")


def test_continue_mode_e2e(e2e):
    tell_questions_at_once()
    set_settings(e2e, "on_failure=continue", "max_tries=1")
    e2e.script_builders(failing=(1,))
    run_id = e2e.start()
    e2e.settle()
    st = e2e.state(run_id)
    assert [st["tasks"][n]["status"] for n in "123"] == ["failed", "passed", "skipped"]
    assert st["status"] == "waiting"
    gate = e2e.open_gates()[0]
    assert gate["kind"] == "merge" and "1 tasks failed" in gate["flags"]
    e2e.answer("approve")
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "failed"
    reason = st["tasks"]["1"]["flagged"]
    assert reason
    summary = e2e.cli("run", "log", run_id, "--summary")[1]
    assert "Task 1" in summary and reason.split(";")[0][:40] in summary
    assert len(trailers(e2e, run_id)) == 1 and len(e2e.adapters.notify.messages) == 2   # the merge question + the run's end


def test_pause_mode_e2e_ack_via_cli(e2e):
    set_settings(e2e, "on_failure=pause", "max_tries=1")
    fail_task_1_first(e2e)
    run_id = e2e.start()
    e2e.settle()
    found = e2e.json("gate", "list")
    assert [g["kind"] for g in found] == ["escalation"] and found[0]["task"] == 1
    assert e2e.state(run_id)["status"] == "waiting" and len(e2e.adapters.notify.messages) == 1
    assert e2e.cli("gate", "answer", found[0]["id"], "acknowledged", "--who", "cli")[0] == 0
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "done", st
    assert [st["tasks"][n]["status"] for n in "123"] == ["passed"] * 3 and st["tasks"]["1"]["tries"] == 2
    assert st["tasks"]["1"]["escalations"] == 1


def test_human_task_e2e(e2e, tmp_path):
    text = (ROOT / "plans" / "e2e-quick.md").read_text()
    head, rest = text.split("## Task 2:")
    task2, task3 = rest.split("## Task 3:")
    task2 = task2.replace("For you: no", "For you: yes").replace(
        "- `python3 -m pytest -q tests/test_whisper.py`", "- Alex has written the whisper function by hand")
    spec_file = tmp_path / "human.md"
    spec_file.write_text(head + "## Task 2:" + task2 + "## Task 3:" + task3)
    e2e.script_builders()
    run_id = e2e.start(str(spec_file))
    e2e.settle()
    found = e2e.open_gates()
    assert [g["kind"] for g in found] == ["human-task"] and found[0]["task"] == 2
    assert e2e.state(run_id)["tasks"]["1"]["status"] == "passed"
    e2e.answer("approve")
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "done", st
    assert [st["tasks"][n]["status"] for n in "123"] == ["passed"] * 3
    assert len(trailers(e2e, run_id)) == 2          # nothing is built for the task that is for Alex


def test_secret_never_leaks_e2e(e2e, phoenix_env):
    secret = "sk-e2e-SECRET-value-0123456789abcdef"
    assert e2e.cli("project", "keys", "e2e", "set", "API_KEY", "--secret", stdin=secret + "\n")[0] == 0
    e2e.git("add", "-A")                       # setting a key adds .env.example; commit it so main is clean
    e2e.git("commit", "-q", "-m", "Add .env.example")
    for n in (1, 2, 3):
        name, text = TESTS[n]
        e2e.claude.script("builder", n, files={**SOURCES[n], f"tests/{name}": text},
                          text=f"The key is {secret}\nSTEP DONE")
    run_id = e2e.start()
    e2e.settle()
    assert e2e.state(run_id)["status"] == "done"
    keys_file = phoenix_env["home"] / "keys" / "e2e.toml"
    assert secret in keys_file.read_text()
    leaks = [p for p in phoenix_env["home"].rglob("*")
             if p.is_file() and p != keys_file and secret.encode() in p.read_bytes()]
    assert leaks == []
    assert secret not in e2e.cli("project", "keys", "e2e")[1]


def test_runner_restart_mid_merge_gate_e2e(e2e):
    tell_questions_at_once()
    set_settings(e2e, "merge=ask")
    e2e.script_builders()
    run_id = e2e.start()
    e2e.settle()
    gate = e2e.open_gates()[0]
    assert gate["kind"] == "merge" and "local only" in gate["why"]
    e2e.runner = Runner(e2e.adapters, ROOT)          # the old runner is gone; a new one starts
    e2e.settle()
    assert e2e.state(run_id)["status"] == "waiting" and len(e2e.open_gates()) == 1
    e2e.answer("approve")
    e2e.settle()
    st = e2e.state(run_id)
    assert st["status"] == "done", st
    assert e2e.git("branch", "--list", f"phoenix/{run_id}").strip() == ""   # merged, so the branch is gone
    assert len(e2e.adapters.notify.messages) == 2     # the merge question (told once, not again after the restart) + the end


def test_quick_run_deploys_on_merge(e2e, tmp_path, monkeypatch):
    """A Quick run of a project with the test deployer on-merge ends done with a deploy event and record."""
    import sys
    from types import SimpleNamespace
    from phoenix9 import deploy, events, paths
    root = tmp_path / "deploy-lib"
    root.mkdir()
    for item in ROOT.iterdir():
        if item.name != "deployers" and not item.name.startswith("."):
            (root / item.name).symlink_to(item)
    (root / "deployers").symlink_to(ROOT / "tests" / "data" / "deployers")
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    sys.modules["deploy_script"] = SimpleNamespace(
        deploy=lambda dctx: {"url": "https://e2e.example", "version": "v1"}, health=lambda d, r: (True, "ok"),
        rollback=lambda d, r, p: {}, preview=lambda d: {}, stop_preview=lambda d, r: None)
    toml = paths.projects() / "e2e" / "phoenix.toml"
    toml.write_text(toml.read_text() + '\n[deploy]\nwith = "scripted"\nmode = "on-merge"\n\n[deploy.settings]\nlive_port = 8080\n')
    e2e.script_builders()
    run_id = e2e.start()
    e2e.settle()
    st = e2e.state(run_id)
    sys.modules.pop("deploy_script", None)
    assert st["status"] == "done", st
    assert [x["status"] for x in st["steps"] if x["step"] == "deploy"] == ["passed"]
    assert [r["ok"] for r in deploy.read_records("e2e")] == [True]
    assert any(e["type"] == "deploy.finished" for e in events.tail(paths.events(), 200))
