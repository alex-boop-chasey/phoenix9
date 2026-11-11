"""Tests for the step session read tool: ops, CLI, API route and registry entry."""
import json

from phoenix9 import atomic
from phoenix9.__main__ import main
from phoenix9.api import server
from phoenix9.ops import common, controls, runs
from tests.helpers import repair_runs as rr

FAKE_TOKEN = "sk-" + "ant-" + "planted0123456789abcdef"   # built at run time, never written whole


def _line(kind, **fields):
    return json.dumps({"type": kind, **fields})


def _seed(tmp_path, text=None):
    """A failed run whose task 1 try 2 has a builder session log where the runner writes it."""
    made = rr.make_run(tmp_path)
    text = text if text is not None else f"I tried to deploy with {FAKE_TOKEN} and it failed."
    lines = [_line("assistant", message={"content": [{"type": "text", "text": text}]}),
             _line("result", result="Checks failed: test_x")]
    atomic.write_text(made["run_dir"] / "logs" / "1-2-builder.jsonl", "\n".join(lines) + "\n")
    atomic.write_text(made["run_dir"] / "logs" / "1-1-builder.jsonl", _line("result", result="first try") + "\n")
    return made


def test_excerpt_is_quoted_and_scrubbed(phoenix_env, tmp_path):
    _seed(tmp_path)
    got = runs.session_excerpt(rr.PROJECT, rr.RUN, 1)
    assert got["quoted"] is True and got["source"] == "logs/1-2-builder.jsonl"
    assert FAKE_TOKEN not in json.dumps(got) and "Checks failed" in got["text"]


def test_named_attempt(phoenix_env, tmp_path):
    _seed(tmp_path)
    assert runs.session_excerpt(rr.PROJECT, rr.RUN, 1, attempt=1)["text"] == "first try"


def test_excerpt_is_capped(phoenix_env, tmp_path):
    _seed(tmp_path, "x" * 50000)
    assert len(runs.session_excerpt(rr.PROJECT, rr.RUN, 1)["text"]) <= runs.SESSION_CHARS


def test_missing_session_and_other_project(phoenix_env, tmp_path):
    _seed(tmp_path)
    for args in ((rr.PROJECT, rr.RUN, 7), ("other", rr.RUN, 1)):
        try:
            runs.session_excerpt(*args)
        except common.NotFound:
            continue
        raise AssertionError("expected NotFound")


def test_log_outside_run_folder_is_refused(phoenix_env, tmp_path):
    made = _seed(tmp_path)
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text(_line("result", result="outside"))
    (made["run_dir"] / "logs" / "3-1-builder.jsonl").symlink_to(outside)
    try:
        runs.session_excerpt(rr.PROJECT, rr.RUN, 3)
    except common.NotFound:
        return
    raise AssertionError("expected NotFound")


def test_cli_json(phoenix_env, tmp_path, capsys):
    _seed(tmp_path)
    assert main(["run", "session", rr.PROJECT, rr.RUN, "--task", "1", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["quoted"] is True and FAKE_TOKEN not in out


def test_route_and_registry_entry():
    assert any(r[2] is server.get_run_session for r in server.ROUTES)
    c = next(c for c in controls.CONTROLS if c.name == "step-session")
    assert c.risk == "read" and c.agent == "tool" and c.card == "session_card"
