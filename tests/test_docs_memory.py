"""Tests for a project's memory (CLAUDE.md and notes/NOW.md) as the agent reads it: cut, scrubbed, never outside."""
import os

import pytest

from phoenix9 import keys
from phoenix9.ops import common, docs
from test_agentaccess import HEADERS as AGENT_HEADERS
from test_api_server import api, dist  # noqa: F401  (fixtures)
from test_api_work import as_agent
from test_ops_logs import proj  # noqa: F401  (fixture)


@pytest.fixture
def demo(proj):
    """The demo project's folder with an empty notes folder."""
    folder = common.project_dir("demo")
    (folder / "notes").mkdir(exist_ok=True)
    return folder


def test_reads_both_files(demo):
    (demo / "notes/NOW.md").write_text("# Now\nWorking on the login page.\n")
    assert docs.project_memory("demo") == {"project": "demo", "claude_md": "# demo\n",
                                           "now_md": "# Now\nWorking on the login page.\n", "cut": False}


def test_missing_files_are_empty(demo):
    (demo / "CLAUDE.md").unlink()
    assert docs.project_memory("demo") == {"project": "demo", "claude_md": "", "now_md": "", "cut": False}


def test_cut_keeps_the_end_of_now_and_the_start_of_claude(demo):
    lines = [f"line {i:05d} " + "x" * 40 for i in range(3000)]
    (demo / "notes/NOW.md").write_text("\n".join(lines) + "\nNEWEST LINE\n")
    (demo / "CLAUDE.md").write_text("FIRST LINE\n" + "\n".join(lines) + "\n")
    out = docs.project_memory("demo")
    assert out["cut"] is True
    assert len(out["now_md"]) <= docs.MEMORY_CHARS and out["now_md"].endswith("NEWEST LINE\n")
    assert "line 00000" not in out["now_md"]
    assert len(out["claude_md"]) <= docs.MEMORY_CHARS and out["claude_md"].startswith("FIRST LINE\n")


def test_planted_key_is_scrubbed(demo):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (demo / "notes/NOW.md").write_text("the key is sekrit-value-12345 ok\n")
    (demo / "CLAUDE.md").write_text("also sekrit-value-12345\n")
    out = docs.project_memory("demo")
    assert "sekrit-value-12345" not in repr(out) and "the key is" in out["now_md"]


def test_symlink_out_of_the_project_refused(demo, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside text\n")
    os.symlink(outside, demo / "notes/NOW.md")
    with pytest.raises(common.OpsError):
        docs.project_memory("demo")
    os.unlink(demo / "notes/NOW.md")
    (demo / "notes").rmdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "NOW.md").write_text("outside text\n")
    os.symlink(elsewhere, demo / "notes")
    with pytest.raises(common.OpsError):
        docs.project_memory("demo")


def test_agent_folder_refused(demo):
    (demo.parent / "home").mkdir()
    (demo.parent / "home/CLAUDE.md").write_text("agent rules\n")
    with pytest.raises(common.Conflict):
        docs.project_memory("home")


@pytest.mark.parametrize("bad", ["", "..", ".hidden", "a/b"])
def test_bad_names_refused(demo, bad):
    with pytest.raises(common.OpsError):
        docs.project_memory(bad)


def test_api_route_for_the_agent(api, demo, monkeypatch):
    (demo / "notes/NOW.md").write_text("Up to step 3.\n")
    as_agent(monkeypatch)
    status, body = api("/api/projects/demo/memory", headers=AGENT_HEADERS)
    assert status == 200 and body["data"]["now_md"] == "Up to step 3.\n"
    assert api("/api/projects/ghost/memory", headers=AGENT_HEADERS)[0] == 404
    assert api("/api/projects/home/memory", headers=AGENT_HEADERS)[0] == 409
