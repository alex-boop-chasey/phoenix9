"""Tests for phoenix9/claude.py: command line, mounts, result reading, running, fallback, usage."""
# parse / run / wait_for_limit tests ported from reference/v8/tests/test_claude.py
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phoenix9 import atomic, claude, state

DATA = Path(__file__).parent / "data" / "stream"
# 2026-10-30 10:00 UTC, so "resets 3:45pm" (read in UTC) means 15:45 the same day.
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)

AI = {"model": "claude-fable-5-1", "fallback_models": ["claude-opus-5-5", "claude-sonnet-5-5"],
      "tools": [], "tools_denied": [], "mcp_servers": [], "claude_md": "library", "skills": [],
      "max_turns": 40, "timeout": 60,
      "advisor": {"on": False, "model": "claude-opus-5-5", "when": ["blocked"], "instructions": ""}}



def _start_local(cmd, cwd, env_files):
    """Start a test program on this machine with the env files' values added (tests only; never Claude)."""
    import os
    import subprocess
    from phoenix9.scrub import read_env_file
    env = dict(os.environ)
    for path in env_files:
        env.update(read_env_file(path))
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def _inner(cmd):
    return cmd[cmd.index("claude"):]


def _pair(inner, flag):
    i = inner.index(flag)
    return inner[i:i + 2]


# ------------------------------------------------------------- build_command
def test_build_command_basics():
    cmd = claude.build_command(AI, "/work/prompt.md", "/work/repo")
    assert cmd[:2] == ["sh", "-c"]
    inner = _inner(cmd)
    assert inner[:2] == ["claude", "-p"]
    assert _pair(inner, "--output-format") == ["--output-format", "stream-json"]
    assert "--verbose" in inner
    assert _pair(inner, "--model") == ["--model", "claude-fable-5-1"]
    assert _pair(inner, "--max-turns") == ["--max-turns", "40"]
    assert _pair(inner, "--permission-mode") == ["--permission-mode", "bypassPermissions"]
    assert "/work/prompt.md" in cmd and "/work/repo" in cmd


def test_build_command_leaves_out_empty_lists():
    inner = _inner(claude.build_command(AI, "p.md", "."))
    for flag in ("--allowedTools", "--disallowedTools", "--mcp-config", "--append-system-prompt-file"):
        assert flag not in inner


def test_build_command_tools_mcp_and_system_prompt():
    ai = dict(AI, tools=["Read", "Edit"], tools_denied=["WebFetch", "Agent"], mcp_servers=["docs"], max_turns=7)
    inner = _inner(claude.build_command(ai, "p.md", ".", system_prompt_file="/work/system.md"))
    assert _pair(inner, "--allowedTools") == ["--allowedTools", "Read,Edit"]
    assert _pair(inner, "--disallowedTools") == ["--disallowedTools", "WebFetch,Agent"]
    assert _pair(inner, "--mcp-config") == ["--mcp-config", claude.MCP_MOUNT]
    assert _pair(inner, "--append-system-prompt-file") == ["--append-system-prompt-file", "/work/system.md"]
    assert _pair(inner, "--max-turns") == ["--max-turns", "7"]


def test_build_command_never_bare():
    full = dict(AI, tools=["Read"], tools_denied=["Agent"], mcp_servers=["x"])
    assert "--bare" not in claude.build_command(full, "p.md", ".", "s.md")
    assert "--bare" not in claude.build_command({}, "p.md", ".")


def test_build_command_feeds_prompt_file_and_cwd(tmp_path):
    """The sh wrapper must cd into cwd and send the prompt file to stdin."""
    (tmp_path / "prompt.md").write_text("hello prompt\n")
    cmd = claude.build_command(AI, str(tmp_path / "prompt.md"), str(tmp_path))
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text('#!/bin/sh\npwd\ncat\necho "$@"\n')
    (fake / "claude").chmod(0o755)
    out = subprocess.run(cmd, capture_output=True, text=True, env={"PATH": f"{fake}:/usr/bin:/bin"},
                         cwd="/").stdout.splitlines()
    assert out[0] == str(tmp_path)
    assert out[1] == "hello prompt"
    assert out[2].startswith("-p --output-format stream-json")


# ------------------------------------------------------------- mcp config and mounts
def test_write_mcp_config(tmp_path):
    registry = {"docs": {"command": "npx", "args": ["docs-mcp"]}, "db": {"url": "http://x"}, "other": {}}
    dest = claude.write_mcp_config(["docs", "db"], registry, tmp_path / "mcp.json")
    assert json.loads(dest.read_text()) == {"mcpServers": {"docs": registry["docs"], "db": registry["db"]}}


def test_write_mcp_config_unknown_name(tmp_path):
    with pytest.raises(ValueError):
        claude.write_mcp_config(["nope"], {}, tmp_path / "mcp.json")


@pytest.fixture
def folders(tmp_path):
    step, project, skills = tmp_path / "step", tmp_path / "project", tmp_path / "skills"
    (project / "code").mkdir(parents=True)
    step.mkdir()
    skills.mkdir()
    return step, project, skills


def _by_dst(mounts):
    return {m.dst: m for m in mounts}


def test_claude_md_library(folders, tmp_path):
    step, project, skills = folders
    (step / "CLAUDE.md").write_text("library rules")
    (project / "code" / "CLAUDE.md").write_text("project rules")
    mounts = claude.session_mounts(dict(AI, claude_md="library"), step, project, tmp_path / "t", skills)
    m = _by_dst(mounts)[f"{claude.CLAUDE_HOME}/CLAUDE.md"]
    assert m.src.read_text() == "library rules" and m.ro


def test_claude_md_project(folders, tmp_path):
    step, project, skills = folders
    (step / "CLAUDE.md").write_text("library rules")
    (project / "code" / "CLAUDE.md").write_text("project rules")
    mounts = claude.session_mounts(dict(AI, claude_md="project"), step, project, tmp_path / "t", skills)
    assert _by_dst(mounts)[f"{claude.CLAUDE_HOME}/CLAUDE.md"].src.read_text() == "project rules"


def test_claude_md_both_is_joined(folders, tmp_path):
    step, project, skills = folders
    (step / "CLAUDE.md").write_text("library rules")
    (project / "code" / "CLAUDE.md").write_text("project rules")
    mounts = claude.session_mounts(dict(AI, claude_md="both"), step, project, tmp_path / "t", skills)
    text = _by_dst(mounts)[f"{claude.CLAUDE_HOME}/CLAUDE.md"].src.read_text()
    assert text.index("library rules") < text.index("project rules")


def test_claude_md_missing_files_give_no_mount(folders, tmp_path):
    step, project, skills = folders
    assert claude.session_mounts(AI, step, project, tmp_path / "t", skills) == []


def test_skills_are_read_only_mounts(folders, tmp_path):
    step, project, skills = folders
    (skills / "testing").mkdir()
    mounts = claude.session_mounts(dict(AI, skills=["testing"]), step, project, tmp_path / "t", skills)
    m = _by_dst(mounts)[f"{claude.CLAUDE_HOME}/skills/testing"]
    assert m.src == skills / "testing" and m.ro


def test_skill_name_cannot_escape(folders, tmp_path):
    step, project, skills = folders
    with pytest.raises(ValueError):
        claude.session_mounts(dict(AI, skills=["../x"]), step, project, tmp_path / "t", skills)


def test_advisor_mount_and_json(folders, tmp_path):
    step, project, skills = folders
    (skills / "advisor").mkdir()
    advisor = {"on": True, "model": "claude-opus-5-5", "when": ["blocked", "before-done"], "instructions": "be brief"}
    mounts = _by_dst(claude.session_mounts(dict(AI, advisor=advisor), step, project, tmp_path / "t", skills))
    skill = mounts[f"{claude.CLAUDE_HOME}/skills/advisor"]
    info = mounts[f"{claude.CLAUDE_HOME}/skills/advisor.json"]
    assert skill.src == skills / "advisor" and skill.ro and info.ro
    assert json.loads(info.src.read_text()) == {"model": "claude-opus-5-5", "when": ["blocked", "before-done"],
                                                "instructions": "be brief"}


def test_advisor_off_mounts_nothing(folders, tmp_path):
    step, project, skills = folders
    assert claude.session_mounts(AI, step, project, tmp_path / "t", skills) == []


# ------------------------------------------------------------- parse
def test_parse_normal_result():
    r = claude.parse(DATA / "normal.jsonl", 0)
    assert r.kind == "ok"
    assert r.text == "Built the page."
    assert r.session_id == "sess-1"
    assert r.cost_usd == pytest.approx(0.1234)
    assert r.turns == 3
    assert r.resets_at is None
    assert r.raw_path == DATA / "normal.jsonl"


def test_parse_rate_limit_with_reset_time():
    r = claude.parse(DATA / "rate-limit.jsonl", 1, now=NOW.timestamp())
    assert r.kind == "rate_limited"
    assert r.resets_at == datetime(2026, 10, 30, 15, 45, tzinfo=timezone.utc)


def test_parse_rate_limit_reset_in_other_time_zone():
    r = claude.parse(DATA / "rate-limit.jsonl", 1, now=NOW.timestamp(), tz="Australia/Brisbane")
    assert r.resets_at == datetime(2026, 10, 31, 5, 45, tzinfo=timezone.utc)


def test_parse_forged_extra_result_line_is_crashed():
    assert claude.parse(DATA / "forged-result.jsonl", 0).kind == "crashed"


def test_parse_cut_off_output_is_crashed():
    r = claude.parse(DATA / "cut-off.jsonl", 0)
    assert r.kind == "crashed"
    assert r.session_id == ""


def test_parse_missing_or_empty_file_is_crashed(tmp_path):
    (tmp_path / "empty.jsonl").write_text("")
    assert claude.parse(tmp_path / "empty.jsonl", 0).kind == "crashed"
    assert claude.parse(tmp_path / "missing.jsonl", 0).kind == "crashed"


def test_parse_error_result():
    r = claude.parse(DATA / "error.jsonl", 1)
    assert r.kind == "error"
    assert r.cost_usd == 1.5


def test_parse_ok_json_but_nonzero_exit_is_error():
    assert claude.parse(DATA / "normal.jsonl", 2).kind == "error"


def _write_result(path, **fields):
    path.write_text(json.dumps({"type": "result", "session_id": "s", **fields}) + "\n")
    return path


def test_parse_hit_limit_text_counts_even_without_is_error(tmp_path):
    f = _write_result(tmp_path / "o.jsonl", is_error=False,
                      result="Claude AI usage: you've hit your weekly limit, resets Mon 9am")
    assert claude.parse(f, 0, now=NOW.timestamp()).kind == "rate_limited"


def test_parse_long_answer_mentioning_429_is_not_rate_limited(tmp_path):
    f = _write_result(tmp_path / "o.jsonl", is_error=False,
                      result="Added a handler for HTTP 429 too many requests. " * 20)
    assert claude.parse(f, 0).kind == "ok"


def test_parse_api_429_status_is_rate_limited(tmp_path):
    f = _write_result(tmp_path / "o.jsonl", is_error=True, api_error_status=429, result="x")
    r = claude.parse(f, 1)
    assert r.kind == "rate_limited"
    assert r.resets_at is None


@pytest.mark.parametrize("text", [
    "There's an issue with the selected model (claude-foo). It may not exist or you may not have access to it.",
    "API Error: 404 model: claude-foo not found",
    "The model claude-foo is not available on your plan",
    "Model overloaded for this model, try again later",
    "invalid model name",
])
def test_parse_model_unavailable(tmp_path, text):
    f = _write_result(tmp_path / "o.jsonl", is_error=True, result=text)
    assert claude.parse(f, 1).kind == "model_unavailable"


def test_parse_model_words_in_successful_answer_are_fine(tmp_path):
    f = _write_result(tmp_path / "o.jsonl", is_error=False, result="The model was not found in the docs.")
    assert claude.parse(f, 0).kind == "ok"


def test_parse_rate_limit_wins_over_model_words(tmp_path):
    f = _write_result(tmp_path / "o.jsonl", is_error=True, result="429 too many requests for this model")
    assert claude.parse(f, 1).kind == "rate_limited"


def test_parse_crashed_uses_stderr_text(tmp_path):
    (tmp_path / "out.jsonl").write_text("")
    (tmp_path / "err").write_text("boom")
    r = claude.parse(tmp_path / "out.jsonl", 1, tmp_path / "err")
    assert (r.kind, r.text) == ("crashed", "boom")


def test_parse_resets_at_iso_time():
    stamp = claude.parse_resets_at("limit resets at 2026-10-30T18:00:00Z", now=NOW.timestamp())
    assert stamp == datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc).timestamp()


def test_parse_resets_at_none():
    assert claude.parse_resets_at("no time here") is None


def test_kinds_include_model_unavailable():
    assert "model_unavailable" in claude.KINDS


# ------------------------------------------------------------- run
def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_normal_session_logs_every_line(tmp_path):
    code = f"import sys; sys.stdout.write(open({str(DATA / 'normal.jsonl')!r}).read())"
    log = tmp_path / "logs" / "builder.jsonl"
    r = claude.run(_py(code), tmp_path, [], log, timeout_min=1, no_output_timeout_min=1, start=_start_local)
    assert r.kind == "ok"
    assert log.read_text() == (DATA / "normal.jsonl").read_text()
    assert r.raw_path == log


def test_run_no_output_stops_quickly(tmp_path):
    code = "import time; print('{\"type\":\"system\"}', flush=True); time.sleep(60)"
    started = time.monotonic()
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl", timeout_min=10, no_output_timeout_min=1 / 60, start=_start_local)
    assert r.kind == "no_output"
    assert time.monotonic() - started < 5
    assert (tmp_path / "out.jsonl").read_text() == '{"type":"system"}\n'


def test_run_total_timeout(tmp_path):
    code = "import time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.1)"
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl", timeout_min=1 / 60, no_output_timeout_min=1, start=_start_local)
    assert r.kind == "timed_out"


def test_run_kills_process_that_ignores_sigint(tmp_path):
    code = ("import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
            "print('x', flush=True); time.sleep(60)")
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl",
                   timeout_min=1, no_output_timeout_min=0.5 / 60, grace_s=0.5, start=_start_local)
    assert r.kind == "no_output"


def test_run_uses_given_starter_and_redacts_secrets_in_saved_stream(tmp_path):
    env = tmp_path / "project.env"
    env.write_text("# test keys\nSTRIPE_KEY=sk_test_abcdef123456\nSHORT=abc\n")
    seen = {}

    def start(cmd, cwd, env_files):
        seen["env_files"] = env_files
        return _start_local(cmd, cwd, env_files)

    code = ("import json, os, sys; k = os.environ['STRIPE_KEY']; print(json.dumps({'type': 'assistant', 'm': k})); "
            "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'key ' + k + ' abc ' + 'extra-secret-99'})); "
            "sys.stderr.write('stderr ' + k)")
    r = claude.run(_py(code), tmp_path, [env], tmp_path / "out.jsonl", 1, 1, start=start, secrets=["extra-secret-99"])
    assert seen["env_files"] == [env]
    assert r.kind == "ok"
    saved = (tmp_path / "out.jsonl").read_text()
    assert "sk_test_abcdef123456" not in saved and "extra-secret-99" not in saved
    assert r.text == "key [secret] abc [secret]"
    assert "sk_test_abcdef123456" not in (tmp_path / "out.jsonl.stderr").read_text()


def test_run_crashed_process_keeps_stderr(tmp_path):
    code = "import sys; sys.stderr.write('claude: not found'); sys.exit(127)"
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl", 1, 1, start=_start_local)
    assert r.kind == "crashed"
    assert r.text == "claude: not found"


# ------------------------------------------------------------- run_with_fallback
def _launcher(kinds):
    tried = []

    def launch(model):
        tried.append(model)
        return claude.Result(kind=kinds.get(model, "ok"))
    return launch, tried


def test_fallback_not_needed():
    launch, tried = _launcher({})
    r = claude.run_with_fallback(AI, launch)
    assert (r.kind, r.model, tried) == ("ok", "claude-fable-5-1", ["claude-fable-5-1"])


def test_fallback_in_order_on_model_unavailable():
    launch, tried = _launcher({"claude-fable-5-1": "model_unavailable", "claude-opus-5-5": "model_unavailable"})
    r = claude.run_with_fallback(AI, launch)
    assert tried == ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"]
    assert (r.kind, r.model) == ("ok", "claude-sonnet-5-5")


def test_fallback_all_unavailable_returns_last():
    launch, tried = _launcher({m: "model_unavailable" for m in ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"]})
    r = claude.run_with_fallback(AI, launch)
    assert r.kind == "model_unavailable" and len(tried) == 3


def test_no_fallback_on_rate_limited():
    launch, tried = _launcher({"claude-fable-5-1": "rate_limited"})
    r = claude.run_with_fallback(AI, launch)
    assert r.kind == "rate_limited"
    assert tried == ["claude-fable-5-1"]


@pytest.mark.parametrize("kind", ["error", "crashed", "timed_out", "no_output"])
def test_no_fallback_on_other_failures(kind):
    launch, tried = _launcher({"claude-fable-5-1": kind})
    assert claude.run_with_fallback(AI, launch).kind == kind
    assert len(tried) == 1


# ------------------------------------------------------------- wait_for_limit
class FakeClock:
    """A clock that only moves when sleep() is called."""

    def __init__(self, start: datetime):
        self.t = start
        self.slept = []

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)


def _limited(resets_at=None):
    return claude.Result(kind="rate_limited", resets_at=resets_at)


def test_wait_for_limit_not_limited_returns_true_at_once():
    clock = FakeClock(NOW)
    assert claude.wait_for_limit(claude.Result(kind="ok"), lambda: None, clock.now, clock.sleep, 30, 12)
    assert clock.slept == []


def test_wait_for_limit_sleeps_until_reset_plus_two_minutes():
    clock = FakeClock(NOW)
    resets = NOW + timedelta(hours=5, minutes=45)
    probes = []
    assert claude.wait_for_limit(_limited(resets), lambda: probes.append(1), clock.now, clock.sleep, 30, 12) is True
    assert clock.t == resets + timedelta(minutes=2)
    assert probes == []


def test_wait_for_limit_probes_when_reset_unknown():
    clock = FakeClock(NOW)
    answers = iter([_limited(), _limited(), claude.Result(kind="ok")])
    assert claude.wait_for_limit(_limited(), lambda: next(answers), clock.now, clock.sleep, 30, 12) is True
    assert clock.t == NOW + timedelta(minutes=90)


def test_wait_for_limit_gives_up_after_max_wait():
    clock = FakeClock(NOW)
    assert claude.wait_for_limit(_limited(), lambda: _limited(), clock.now, clock.sleep, 30, 12) is False
    assert clock.t == NOW + timedelta(hours=12)


def test_wait_for_limit_reset_beyond_max_wait_probes_then_gives_up():
    clock = FakeClock(NOW)
    assert claude.wait_for_limit(_limited(NOW + timedelta(hours=20)), lambda: _limited(),
                                 clock.now, clock.sleep, 60, 12) is False
    assert clock.t == NOW + timedelta(hours=12)


def test_wait_for_limit_probe_learns_reset_time():
    clock = FakeClock(NOW)
    resets = NOW + timedelta(hours=2)
    assert claude.wait_for_limit(_limited(), lambda: _limited(resets), clock.now, clock.sleep, 30, 12) is True
    assert clock.t == resets + timedelta(minutes=2)


def test_wait_for_limit_defaults():
    clock = FakeClock(NOW)
    assert claude.wait_for_limit(_limited(), lambda: _limited(), clock.now, clock.sleep) is False
    assert clock.slept == [1800] * 24


# ------------------------------------------------------------- record_usage
def test_record_usage_adds_to_state_and_writes_result_json(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    atomic.write_json(run / "state.json", state.new_state("r1", "demo"))
    attempt = run / "tasks" / "1" / "attempt-1"
    attempt.mkdir(parents=True)
    claude.record_usage(run, claude.Result(kind="ok", session_id="s1", cost_usd=0.25, turns=4, model="m"), attempt)
    claude.record_usage(run, claude.Result(kind="error", session_id="s2", cost_usd=0.5, turns=9))
    assert state.load(run)["usage"] == {"cost_usd": pytest.approx(0.75), "sessions": 2}
    saved = json.loads((attempt / "result.json").read_text())
    assert (saved["kind"], saved["session_id"], saved["turns"], saved["model"]) == ("ok", "s1", 4, "m")
    assert not (run / "tasks" / "1" / "attempt-2").exists()


def test_supported_tools_are_unique_plain_names_with_text():
    names = [n for n, _label, _help in claude.SUPPORTED_TOOLS]
    assert len(names) == len(set(names)) and all(n.isalpha() for n in names)
    assert all(label and help_ for _n, label, help_ in claude.SUPPORTED_TOOLS)
    cmd = claude.build_command(dict(AI, tools=names[:2], tools_denied=[names[-1]]), "/p.md", "/r")
    assert cmd[cmd.index("--allowedTools") + 1] == ",".join(names[:2])
    assert cmd[cmd.index("--disallowedTools") + 1] == names[-1]


def test_parse_two_turn_session_with_numbered_results_is_ok():
    """Claude Code writes one result line per turn (result_index 0, 1, ...); the last one is the answer."""
    r = claude.parse(DATA / "two-turns-result.jsonl", 0)
    assert r.kind != "crashed"
    assert "STEP DONE" in r.text


@pytest.mark.parametrize("name", ["two-turns-bad-order.jsonl", "two-turns-other-session.jsonl"])
def test_parse_numbered_results_out_of_order_or_mixed_sessions_is_crashed(name):
    assert claude.parse(DATA / name, 0).kind == "crashed"
