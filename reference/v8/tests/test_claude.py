import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phoenix import claude, runs
from phoenix.state import load_json

DATA = Path(__file__).parent / "data" / "stream"
# 2026-10-30 10:00 UTC, so "resets 3:45pm" (read in UTC) means 15:45 the same day.
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- build_command
def test_build_command_flags():
    cmd = claude.build_command("/work/prompt.md", "/work/repo", 40, ["Read", "Edit"], ["WebFetch", "Agent"],
                               append_system_prompt_file="/work/system.md")
    assert cmd[:2] == ["sh", "-c"]
    inner = cmd[cmd.index("claude"):]
    assert inner[:2] == ["claude", "-p"]
    for pair in (["--output-format", "stream-json"], ["--permission-mode", "bypassPermissions"],
                 ["--max-turns", "40"], ["--disallowedTools", "WebFetch,Agent"],
                 ["--allowedTools", "Read,Edit"], ["--append-system-prompt-file", "/work/system.md"]):
        i = inner.index(pair[0])
        assert inner[i:i + 2] == pair
    assert "--verbose" in inner
    assert "--bare" not in cmd
    assert "/work/prompt.md" in cmd and "/work/repo" in cmd


def test_build_command_leaves_out_empty_options():
    cmd = claude.build_command("p.md", ".", 5, [], [])
    assert "--allowedTools" not in cmd
    assert "--disallowedTools" not in cmd
    assert "--append-system-prompt-file" not in cmd


def test_build_command_feeds_prompt_file_and_cwd(tmp_path):
    """The sh wrapper must cd into cwd and send the prompt file to stdin."""
    (tmp_path / "prompt.md").write_text("hello prompt\n")
    cmd = claude.build_command(str(tmp_path / "prompt.md"), str(tmp_path), 1, [], [])
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text('#!/bin/sh\npwd\ncat\necho "$@"\n')
    (fake / "claude").chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin"}
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd="/").stdout.splitlines()
    assert out[0] == str(tmp_path)
    assert out[1] == "hello prompt"
    assert out[2].startswith("-p --output-format stream-json")


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
    # 3:45pm in Brisbane (UTC+10) is 05:45 UTC; that is before NOW, so it is the next day.
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


def test_parse_hit_limit_text_counts_even_without_is_error(tmp_path):
    f = tmp_path / "out.jsonl"
    f.write_text(json.dumps({"type": "result", "is_error": False, "result":
                             "Claude AI usage: you've hit your weekly limit, resets Mon 9am", "session_id": "s"}) + "\n")
    assert claude.parse(f, 0, now=NOW.timestamp()).kind == "rate_limited"


def test_parse_long_answer_mentioning_429_is_not_rate_limited(tmp_path):
    f = tmp_path / "out.jsonl"
    text = "Added a handler for HTTP 429 too many requests. " * 20
    f.write_text(json.dumps({"type": "result", "is_error": False, "result": text}) + "\n")
    assert claude.parse(f, 0).kind == "ok"


def test_parse_api_429_status_is_rate_limited(tmp_path):
    f = tmp_path / "out.jsonl"
    f.write_text(json.dumps({"type": "result", "is_error": True, "api_error_status": 429, "result": "x"}) + "\n")
    r = claude.parse(f, 1)
    assert r.kind == "rate_limited"
    assert r.resets_at is None


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


# ------------------------------------------------------------- run
def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_normal_session_logs_every_line(tmp_path):
    code = f"import sys; sys.stdout.write(open({str(DATA / 'normal.jsonl')!r}).read())"
    log = tmp_path / "logs" / "builder.jsonl"
    r = claude.run(_py(code), tmp_path, [], log, timeout_min=1, no_output_timeout_min=1)
    assert r.kind == "ok"
    assert log.read_text() == (DATA / "normal.jsonl").read_text()
    assert r.raw_path == log


def test_run_no_output_stops_within_two_seconds(tmp_path):
    code = "import sys, time; print('{\"type\":\"system\"}', flush=True); time.sleep(60)"
    started = time.monotonic()
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl",
                   timeout_min=10, no_output_timeout_min=1 / 60)
    assert r.kind == "no_output"
    assert time.monotonic() - started < 2
    assert (tmp_path / "out.jsonl").read_text() == '{"type":"system"}\n'


def test_run_total_timeout(tmp_path):
    code = "import time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.1)"
    started = time.monotonic()
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl",
                   timeout_min=1 / 60, no_output_timeout_min=1)
    assert r.kind == "timed_out"
    assert time.monotonic() - started < 2


def test_run_kills_process_that_ignores_sigint(tmp_path):
    code = ("import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
            "print('x', flush=True); time.sleep(60)")
    started = time.monotonic()
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl",
                   timeout_min=1, no_output_timeout_min=0.5 / 60, grace_s=0.5)
    assert r.kind == "no_output"
    assert time.monotonic() - started < 3


def test_run_uses_given_starter_and_redacts_env_values(tmp_path):
    env = tmp_path / "project.env"
    env.write_text("# test keys\nSTRIPE_KEY=sk_test_abcdef123456\nSHORT=abc\n")
    seen = {}

    def start(cmd, cwd, env_files):
        seen["args"] = (cmd, cwd, env_files)
        return claude.start_local(cmd, cwd, env_files)

    code = ("import json, os; print(json.dumps({'type': 'result', 'is_error': False, "
            "'result': 'key ' + os.environ['STRIPE_KEY'] + ' abc'}))")
    r = claude.run(_py(code), tmp_path, [env], tmp_path / "out.jsonl", 1, 1, start=start)
    assert seen["args"][2] == [env]
    assert r.kind == "ok"
    assert "sk_test_abcdef123456" not in (tmp_path / "out.jsonl").read_text()
    assert r.text == "key [redacted] abc"


def test_run_crashed_process_keeps_stderr(tmp_path):
    code = "import sys; sys.stderr.write('claude: not found'); sys.exit(127)"
    r = claude.run(_py(code), tmp_path, [], tmp_path / "out.jsonl", 1, 1)
    assert r.kind == "crashed"
    assert r.text == "claude: not found"


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
    ok = claude.wait_for_limit(_limited(resets), lambda: probes.append(1), clock.now, clock.sleep, 30, 12)
    assert ok is True
    assert clock.t == resets + timedelta(minutes=2)
    assert probes == []


def test_wait_for_limit_probes_when_reset_unknown():
    clock = FakeClock(NOW)
    answers = iter([_limited(), _limited(), claude.Result(kind="ok")])
    ok = claude.wait_for_limit(_limited(), lambda: next(answers), clock.now, clock.sleep, 30, 12)
    assert ok is True
    assert clock.t == NOW + timedelta(minutes=90)


def test_wait_for_limit_gives_up_after_max_wait():
    clock = FakeClock(NOW)
    ok = claude.wait_for_limit(_limited(), lambda: _limited(), clock.now, clock.sleep, 30, 12)
    assert ok is False
    assert clock.t == NOW + timedelta(hours=12)


def test_wait_for_limit_reset_beyond_max_wait_probes_then_gives_up():
    clock = FakeClock(NOW)
    ok = claude.wait_for_limit(_limited(NOW + timedelta(hours=20)), lambda: _limited(),
                               clock.now, clock.sleep, 60, 12)
    assert ok is False
    assert clock.t == NOW + timedelta(hours=12)


def test_wait_for_limit_probe_learns_reset_time():
    clock = FakeClock(NOW)
    resets = NOW + timedelta(hours=2)
    ok = claude.wait_for_limit(_limited(), lambda: _limited(resets), clock.now, clock.sleep, 30, 12)
    assert ok is True
    assert clock.t == resets + timedelta(minutes=2)


def test_wait_for_limit_reads_settings_from_config(phoenix_home):
    (phoenix_home / "config").mkdir(parents=True)
    (phoenix_home / "config" / "phoenix.toml").write_text("usage_probe_min = 10\nusage_max_wait_h = 1\n")
    clock = FakeClock(NOW)
    assert claude.wait_for_limit(_limited(), lambda: _limited(), clock.now, clock.sleep) is False
    assert clock.slept == [600] * 6


# ------------------------------------------------------------- record_usage
def test_record_usage_appends_and_adds_cost():
    rid = runs.new_run_id()
    claude.record_usage(rid, claude.Result(kind="ok", session_id="s1", cost_usd=0.25, turns=4))
    claude.record_usage(rid, claude.Result(kind="error", session_id="s2", cost_usd=0.5, turns=9))
    folder = runs.run_dir(rid)
    lines = [json.loads(l) for l in (folder / "usage.jsonl").read_text().splitlines()]
    assert [l["session_id"] for l in lines] == ["s1", "s2"]
    assert set(lines[0]) == {"at", "session_id", "kind", "cost_usd", "turns"}
    assert lines[1]["kind"] == "error" and lines[1]["turns"] == 9
    assert load_json(folder / "run.json", None)["cost_usd"] == pytest.approx(0.75)
