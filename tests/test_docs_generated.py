"""The generated agent reference files match what the code would write now."""
from pathlib import Path

from phoenix9 import docsgen, routes
from phoenix9.__main__ import main

FILES = ("commands.md", "settings.md", "steps.md", "pages.md", "cards.md")


def test_shipped_files_match_code(tmp_path):
    docsgen.generate(tmp_path)
    for name in FILES:
        assert (docsgen.SKILL_DIR / name).read_text() == (tmp_path / name).read_text(), f"{name} is stale: run `phoenix docs generate`"


def test_version_line_first(tmp_path):
    docsgen.generate(tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_text().startswith("<!-- phoenix 9.")


def test_cli_writes_files(tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["docs", "generate", "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == sorted(FILES)


def test_every_route_described():
    assert {n for n, _ in routes.ROUTES} == set(docsgen.PAGE_TEXT)


def test_commands_cover_groups():
    text = docsgen.commands_body()
    assert "`phoenix docs generate`" in text and "`phoenix agent send`" in text
