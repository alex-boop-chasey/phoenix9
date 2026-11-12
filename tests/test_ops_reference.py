"""Reference ops: files and links in a project, refusals as OpsError, and the command records."""
import json

import pytest

from phoenix9 import paths
from phoenix9.ops import common, reference as ops


@pytest.fixture
def proj():
    (paths.projects() / "demo").mkdir()
    return "demo"


def commands():
    """The commands recorded so far."""
    log = paths.logs() / "commands.jsonl"
    return [json.loads(l)["command"] for l in log.read_text().splitlines()] if log.exists() else []


def test_file_round_trip(proj):
    entry = ops.add(proj, "tokens.json", b'{"a": 1}', "cli")
    assert entry["name"] == "tokens.json"
    assert [f["name"] for f in ops.files(proj)] == ["tokens.json"]
    assert ops.show(proj)["links"] == []
    assert ops.remove(proj, "tokens.json", "cli")["removed"] is True
    assert ops.files(proj) == []
    assert commands() == ["reference add demo tokens.json", "reference remove demo tokens.json"]


def test_link_round_trip(proj):
    result = ops.add_links(proj, "https://example.com/a | brand", "cli")
    assert [l["url"] for l in ops.links(proj)] == ["https://example.com/a"] and result["skipped"] == 0
    ops.remove_link(proj, "https://example.com/a", "cli")
    assert ops.links(proj) == []


def test_refusals_are_ops_errors(proj):
    for call in (lambda: ops.add(proj, "run.exe", b"x", "cli"),
                 lambda: ops.add(proj, "a.css", b"", "cli"),
                 lambda: ops.remove(proj, "missing.css"),
                 lambda: ops.add_links(proj, "no links here", "cli"),
                 lambda: ops.remove_link(proj, "https://example.com/x")):
        with pytest.raises(common.OpsError):
            call()


def test_unknown_project_is_refused():
    with pytest.raises(common.OpsError):
        ops.files("nope")
