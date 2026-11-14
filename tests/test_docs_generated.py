"""The generated reference files come from the code; `phoenix docs generate` with no folder writes only controls.json."""
from pathlib import Path

from phoenix9 import controlsgen, docsgen, routes
from phoenix9.__main__ import main

FILES = ("commands.md", "settings.md", "steps.md", "pages.md", "cards.md")


def test_generate_is_repeatable(tmp_path):
    docsgen.generate(tmp_path / "a")
    docsgen.generate(tmp_path / "b")
    for name in FILES:
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text(), name


def test_cli_without_out_writes_only_controls(tmp_path, monkeypatch):
    target = tmp_path / "controls.json"
    monkeypatch.setattr(controlsgen, "write", lambda: (target.write_text("{}"), target)[1])
    monkeypatch.setattr(docsgen, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reference files")))
    assert main(["docs", "generate"]) == 0
    assert target.read_text() == "{}"


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
    assert "`phoenix docs generate`" in text and "`phoenix chat open`" in text
