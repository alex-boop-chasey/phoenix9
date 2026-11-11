"""Tests for search: each kind is found, secrets and outside paths never show, queries are plain text."""
import json

import pytest
from helpers.search_seed import SECRET, seed

from phoenix9 import routes, search
from phoenix9.ops.common import OpsError


def kinds_of(found):
    """The kinds of a list of results."""
    return sorted(r["kind"] for r in found)


def test_each_kind_is_found(phoenix_env):
    seed()
    assert kinds_of(search.search("telescope")) == ["project"]
    assert kinds_of(search.search("lunar")) == ["run"]
    assert kinds_of(search.search("zebra")) == ["note"]
    assert kinds_of(search.search("tides")) == ["research"]
    assert kinds_of(search.search("quokka")) == ["log"]
    assert kinds_of(search.search("compost")) == ["note"]


def test_result_shape_and_pages_pass_the_routes_check(phoenix_env):
    seed()
    found = search.search("moon") + search.search("quokka") + search.search("zebra") + search.search("alpha")
    assert found
    for item in found:
        assert set(item) == {"kind", "title", "snippet", "project", "page"}
        routes.resolve(item["page"]["to"], item["page"]["params"])
    note = search.search("zebra")[0]
    assert note["page"] == {"to": "doc", "params": {"path": "notes:alpha/ideas.md"}}


def test_kind_filter_and_limit(phoenix_env):
    seed()
    assert kinds_of(search.search("moon", ["research"])) == ["research"]
    assert len(search.search("alpha", limit=1)) == 1
    assert len(search.search("a" * 2, limit=500)) <= 50
    with pytest.raises(OpsError):
        search.search("moon", ["nope"])


def test_a_planted_token_never_appears(phoenix_env):
    seed()
    for q in ("quokka", "token", "started", SECRET):
        assert SECRET not in json.dumps(search.search(q))


def test_paths_never_yield_results(phoenix_env, tmp_path):
    folders = seed()
    (tmp_path / "outside.md").write_text("# Outside\n\nsneaky outsider words\n")
    (folders["alpha"] / "notes" / "link.md").symlink_to(tmp_path / "outside.md")
    (folders["alpha"] / "notes" / "linked").symlink_to(tmp_path)
    for q in ("../", "/etc/passwd", "../outside.md", "sneaky outsider"):
        assert search.search(q) == []


def test_skipped_folders_and_big_files(phoenix_env):
    folders = seed()
    notes = folders["alpha"] / "notes"
    (notes / "logs").mkdir()
    (notes / "logs" / "a.md").write_text("hidden-in-logs\n")
    (notes / ".secret").mkdir()
    (notes / ".secret" / "a.md").write_text("hidden-in-dot\n")
    (notes / "big.md").write_text("hidden-in-big " + "x" * (search.MAX_FILE_BYTES + 1))
    for q in ("hidden-in-logs", "hidden-in-dot", "hidden-in-big"):
        assert search.search(q) == []


def test_a_regex_looking_query_is_text(phoenix_env):
    folders = seed()
    (folders["alpha"] / "notes" / "re.md").write_text("# Re\n\nuse a.*b here\n")
    assert len(search.search("a.*b")) == 1
    assert search.search("^ze") == []
    assert search.search("zeb[r]a") == []


def test_bad_queries_are_plain_errors(phoenix_env):
    seed()
    for bad in ("", " a ", "x" * 101, None):
        with pytest.raises(OpsError):
            search.search(bad)


def test_snippets_are_one_short_line(phoenix_env):
    folders = seed()
    (folders["alpha"] / "notes" / "long.md").write_text("# Long\n\nfirst\n" + "word " * 200 + "needle " + "more " * 200 + "\n")
    hit = search.search("needle")[0]
    assert "\n" not in hit["snippet"] and len(hit["snippet"]) <= search.SNIPPET + 6


def test_nothing_is_written(phoenix_env):
    seed()
    from phoenix9 import paths
    before = sorted(p.as_posix() for p in paths.home().rglob("*"))
    search.search("quokka")
    assert sorted(p.as_posix() for p in paths.home().rglob("*")) == before
