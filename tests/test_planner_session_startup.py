"""The Planner's Claude session dies at startup (no stream output, a reason only on stderr): Phoenix keeps the
reason, falls back to the next model when the command refused its model or an option, and says why it failed."""
import json
import tomllib
from pathlib import Path

import pytest

from fakes import FakeDocker
from helpers.stepunit import load, make_ctx, make_work
from phoenix9 import adapters as adapters_mod, aistep, claude, docker, paths
from phoenix9.claude import Result

REPO = Path(__file__).resolve().parents[1]
IMAGE = "phoenix9-step-python:1"
SID = "0d6f8e3a-4c21-4b7e-9a5f-2b1c3d4e5f60"
SECRET = "sk_test_" + "planted4455667788"          # built at run time, never written whole
REFUSED_MODEL = "Error: the model claude-fable-5-1 is not available for this account\n"
REFUSED_OPTION = "error: unknown option '--append-system-prompt-file'\n"


def planner_ai(model="claude-fable-5-1", fallback=("claude-opus-5-5",)) -> dict:
    """The planner step's ai block with the run's models (as rebirth-site's settings.json had them)."""
    ai = tomllib.loads((REPO / "steps" / "planner" / "step.toml").read_text())["ai"]
    return {**ai, "model": model, "fallback_models": list(fallback)}


def result_line(sid=SID, text="PLAN DONE", cost=0.3) -> str:
    """A good stream-json log: the init line and one result line."""
    return (json.dumps({"type": "system", "subtype": "init", "session_id": sid}) + "\n"
            + json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                          "session_id": sid, "total_cost_usd": cost, "num_turns": 2}) + "\n")


def models_tried(fake: FakeDocker) -> list[str]:
    """The --model value of every container the fake runner started, in order."""
    return [argv[i + 1] for argv in fake.argvs for i, a in enumerate(argv[:-1]) if a == "--model"]


@pytest.fixture
def files(tmp_path):
    """A read-only workspace, a prompt, a project env file with a secret, and the claude env file."""
    ws = tmp_path / "ws"
    ws.mkdir()
    prompt = tmp_path / "planner-prompt.md"
    prompt.write_text("plan this")
    env = tmp_path / "proj.env"
    env.write_text(f"STRIPE_KEY={SECRET}\n")
    paths.secrets().mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=" + "fake-" + "login\n")
    return {"ws": ws, "prompt": prompt, "env": env}


def launch(fake: FakeDocker, files, ai=None) -> Result:
    """Run the real Claude adapter (the one the Planner step uses) over the fake docker runner."""
    return adapters_mod.Claude().launch(
        fake, ai=ai or planner_ai(), project="rebirth-site", run_id="20261115-014243-building", task=0, attempt=1,
        role="planner", image=IMAGE, workspace=files["ws"], prompt_file=files["prompt"],
        step_dir=REPO / "steps" / "planner", project_dir=files["ws"].parent, env_files=[files["env"]],
        workspace_ro=True)


# ------------------------------------------------------------- the crash, reproduced and fixed
def test_startup_crash_with_refused_model_falls_back_to_the_next_model(files):
    """The CLI exits at once with no stream output and the refusal only on stderr: the fallback model runs."""
    fake = FakeDocker()
    fake.outputs = ["", result_line()]
    fake.errors = [REFUSED_MODEL, ""]
    fake.exit_codes = [1, 0]
    r = launch(fake, files)
    assert models_tried(fake) == ["claude-fable-5-1", "claude-opus-5-5"]
    assert (r.kind, r.model, r.session_id) == ("ok", "claude-opus-5-5", SID)
    assert r.cost_usd == 0.3


def test_startup_crash_with_refused_option_falls_back_too(files):
    """An option the command cannot use is treated like an unavailable model: the next model is tried."""
    fake = FakeDocker()
    fake.outputs = ["", result_line()]
    fake.errors = [REFUSED_OPTION, ""]
    fake.exit_codes = [1, 0]
    r = launch(fake, files)
    assert models_tried(fake) == ["claude-fable-5-1", "claude-opus-5-5"]
    assert r.kind == "ok" and r.model == "claude-opus-5-5"


def test_every_model_refused_at_startup_returns_the_reason(files):
    fake = FakeDocker()
    fake.outputs = ["", ""]
    fake.errors = [REFUSED_MODEL, "Error: the model claude-opus-5-5 is not available for this account\n"]
    fake.exit_codes = [1, 1]
    r = launch(fake, files)
    assert models_tried(fake) == ["claude-fable-5-1", "claude-opus-5-5"]
    assert r.kind == "model_unavailable" and r.model == "claude-opus-5-5"
    assert "claude-opus-5-5 is not available" in r.text


def test_silent_startup_crash_stays_crashed_without_a_fallback(files):
    """Nothing on stdout or stderr and a non-zero exit: that is a crash, and no other model is tried."""
    fake = FakeDocker()
    fake.outputs = [""]
    fake.exit_codes = [1]
    r = launch(fake, files)
    assert models_tried(fake) == ["claude-fable-5-1"]
    assert (r.kind, r.text, r.model) == ("crashed", "", "claude-fable-5-1")
    assert r.cost_known is False


def test_stderr_is_kept_beside_the_stream_log_and_scrubbed(files):
    """The container's stderr lands in logs/<task>-<attempt>-<role>.jsonl.stderr with secrets removed."""
    fake = FakeDocker()
    fake.outputs = [""]
    fake.errors = [f"Error: cannot start, key {SECRET} rejected\n"]
    fake.exit_codes = [1]
    r = launch(fake, files)
    assert r.kind == "crashed"
    assert r.raw_path.name == "0-1-planner.jsonl" and r.raw_path.read_text() == ""
    err = docker.stderr_path(r.raw_path)
    run_call = [c for c in fake.calls if c[0] == "run"][0]
    assert run_call[1][2] == err                       # the runner was asked to keep stderr there
    assert err.is_file() and SECRET not in err.read_text() and "[secret]" in err.read_text()
    assert SECRET not in r.text and "cannot start" in r.text


def test_old_stderr_is_not_kept_for_a_new_container(files):
    fake = FakeDocker()
    fake.outputs = ["", ""]
    fake.errors = ["first try said this\n", ""]
    fake.exit_codes = [1, 1]
    r = launch(fake, files, planner_ai(fallback=()))
    assert r.kind == "crashed"
    launch(fake, files, planner_ai(fallback=()))
    assert docker.stderr_path(r.raw_path).read_text() == ""


# ------------------------------------------------------------- the parser's part
@pytest.mark.parametrize("text", [REFUSED_MODEL, REFUSED_OPTION, "Invalid model name: claude-fable-5-1",
                                  "error: option '--max-turns' argument missing / requires a value"])
def test_parse_empty_log_with_refusal_on_stderr_is_model_unavailable(tmp_path, text):
    (tmp_path / "out.jsonl").write_text("")
    (tmp_path / "out.jsonl.stderr").write_text(text)
    r = claude.parse(tmp_path / "out.jsonl", 1, tmp_path / "out.jsonl.stderr")
    assert r.kind == "model_unavailable" and r.text == text


@pytest.mark.parametrize("text,rc", [("", 1), ("Segmentation fault", 139), (REFUSED_MODEL, 0),
                                     ("TypeError: Cannot read properties of undefined", 1)])
def test_parse_empty_log_without_a_refusal_is_crashed(tmp_path, text, rc):
    """No reason, a plain crash, or a clean exit without a result: never a fallback."""
    (tmp_path / "out.jsonl").write_text("")
    (tmp_path / "out.jsonl.stderr").write_text(text)
    assert claude.parse(tmp_path / "out.jsonl", rc, tmp_path / "out.jsonl.stderr").kind == "crashed"


def test_parse_refusal_in_a_real_result_is_still_error(tmp_path):
    """stderr words only count when the session wrote no result; a finished session is judged by its result."""
    line = json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "Checks failed",
                       "session_id": SID, "total_cost_usd": 0.1})
    (tmp_path / "out.jsonl").write_text(line + "\n")
    (tmp_path / "out.jsonl.stderr").write_text(REFUSED_OPTION)
    assert claude.parse(tmp_path / "out.jsonl", 1, tmp_path / "out.jsonl.stderr").kind == "error"


# ------------------------------------------------------------- the step says why
def test_planner_failure_line_says_what_the_command_said(tmp_path, adapters):
    code = load("planner")
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "planner")
    got = code.after(ctx, Result(kind="crashed", text="node: error: unknown option '--foo'\n  at main\n"))
    assert got.status == "fail"
    assert got.reasons == ["The planner session ended before it finished (crashed). "
                           "It said: node: error: unknown option '--foo' at main"]


def test_planner_failure_line_without_a_reason_is_unchanged(tmp_path, adapters):
    code = load("planner")
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "planner")
    got = code.after(ctx, Result(kind="crashed", text=""))
    assert got.reasons == ["The planner session ended before it finished (crashed)."]


def test_session_reason_is_one_scrubbed_line_and_empty_when_ok():
    assert aistep.session_reason(Result(kind="ok", text="all good")) == ""
    assert aistep.session_reason(Result(kind="error", text="  a\n\n b  c\n")) == "a b c"
    long = "x" * 1000
    assert aistep.session_reason(Result(kind="crashed", text=long)) == "x" * aistep.REASON_CHARS
    assert aistep.session_reason(Result(kind="crashed", text="token sk-ant-" + "api03-" + "a" * 40 + " leaked")) == "token [secret] leaked"


# ------------------------------------------------------------- the whole Planner step, as the runner runs it
def planner_ctx(tmp_path, adapters, logged: list[str]):
    """A Planner step context like rebirth-site's run: the run's spec, the step's folder and ai block, a real
    Claude adapter over the fake docker runner, and a `log` that collects logs/planner.log lines."""
    from phoenix9.stepctx import StepInfo
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "planner")
    ctx.run.folder.mkdir(parents=True, exist_ok=True)
    (ctx.run.folder / "spec.md").write_text("# Rebirth site\n\nBuild a new website.\n")
    ctx.step = StepInfo("planner", "ai", folder=REPO / "steps" / "planner", ai=planner_ai())
    ctx.task = None
    ctx.adapters.claude = adapters_mod.Claude()
    ctx.log = logged.append
    paths.secrets().mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "claude.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=" + "fake-" + "login\n")
    return ctx


def test_planner_step_startup_crash_with_a_refused_model_runs_the_fallback_model(tmp_path, adapters):
    """rebirth-site's crash: the container exits at once, non-zero, with an empty 0-1-planner.jsonl. With the
    refusal kept from stderr the step moves on to claude-opus-5-5 instead of failing as `crashed`."""
    from phoenix9 import runner
    logged: list[str] = []
    ctx = planner_ctx(tmp_path, adapters, logged)
    fake = ctx.adapters.docker
    fake.outputs = ["", result_line(text="PLAN DONE")]
    fake.errors = [REFUSED_MODEL, ""]
    fake.exit_codes = [1, 0]
    got = runner.run_ai_step(ctx, load("planner"))
    assert models_tried(fake) == ["claude-fable-5-1", "claude-opus-5-5"]
    logs = [Path(c[1][1]) for c in fake.calls if c[0] == "run"]
    assert [p.name for p in logs] == ["0-1-planner.jsonl"] * 2       # same log, the fallback run overwrites
    assert logs[0].read_text() == result_line(text="PLAN DONE") and docker.stderr_path(logs[0]).read_text() == ""
    assert got.status == "fail" and got.reasons == ["The planner wrote no /out/spec.md."]   # past the crash
    assert any(line == "session ended: ok" for line in logged)


def test_planner_step_silent_startup_crash_fails_and_says_so(tmp_path, adapters):
    """Nothing on stdout or stderr: still a crash, no fallback, and the step's line says what the command said
    (nothing, here) rather than inventing a reason."""
    from phoenix9 import runner
    logged: list[str] = []
    ctx = planner_ctx(tmp_path, adapters, logged)
    fake = ctx.adapters.docker
    fake.outputs = [""]
    fake.exit_codes = [1]
    got = runner.run_ai_step(ctx, load("planner"))
    assert models_tried(fake) == ["claude-fable-5-1"]
    assert got.status == "fail" and got.reasons == ["The planner session ended before it finished (crashed)."]
    assert "session ended: crashed" in logged


def test_planner_step_crash_with_an_error_on_stderr_quotes_it(tmp_path, adapters):
    """A real crash (not a refused model or option) stays `crashed` but planner.log and the failure line quote it."""
    from phoenix9 import runner
    logged: list[str] = []
    ctx = planner_ctx(tmp_path, adapters, logged)
    fake = ctx.adapters.docker
    fake.outputs = [""]
    fake.errors = ["node:internal/modules: Error: Cannot find module 'yoga'\n    at Module._resolveFilename\n"]
    fake.exit_codes = [1]
    got = runner.run_ai_step(ctx, load("planner"))
    assert models_tried(fake) == ["claude-fable-5-1"]
    assert got.status == "fail"
    assert got.reasons[0].startswith("The planner session ended before it finished (crashed). It said: node:internal")
    assert any(line.startswith("session ended: crashed: node:internal/modules: Error: Cannot find module 'yoga'")
               for line in logged)
