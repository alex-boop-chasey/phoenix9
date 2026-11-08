"""Tests for document ids, the docs API and CLI, scrubbing, download headers and gate doc ids."""
import json
import os

import pytest

from phoenix9 import keys, paths
from phoenix9.__main__ import main
from phoenix9.ops import common, docs
from test_ops_logs import RUN, proj  # noqa: F401  (fixture)
from test_api_server import api, dist  # noqa: F401  (fixtures)


@pytest.fixture
def folder(proj):
    """The run folder with a state file and a few documents, plus the project's notes folder."""
    run = paths.runs("demo") / RUN
    (run / "state.json").write_text("{}")
    (run / "plan.md").write_text("# The plan\n\nSteps.\n")
    (run / "summary.md").write_text("# Summary\n")
    (run / "tasks/1/attempt-1/notes.txt").write_text("plain notes\n")
    notes = paths.projects() / "demo" / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "idea.md").write_text("# Idea\n")
    return run


def test_list_and_show(folder):
    rows = docs.list(RUN)
    assert [r["id"] for r in rows][:2] == [f"run:{RUN}/plan.md", f"run:{RUN}/summary.md"]
    assert rows[0]["title"] == "The plan" and rows[0]["size"] > 0
    assert f"run:{RUN}/tasks/1/attempt-1/notes.txt" in [r["id"] for r in rows]
    assert not any(r["id"].endswith(".log") or "/logs/" in r["id"] for r in rows)
    assert docs.show(f"run:{RUN}/plan.md") == {"id": f"run:{RUN}/plan.md", "title": "The plan", "text": "# The plan\n\nSteps.\n"}
    assert docs.show("notes:demo/idea.md")["title"] == "Idea"


@pytest.mark.parametrize("bad", ["plan.md", "run:", f"run:{RUN}", f"run:{RUN}/../x.md", f"run:{RUN}/a/../plan.md",
                                 f"run:{RUN}//etc/passwd.md", f"run:{RUN}/", "notes:demo/../../x.md",
                                 f"run:{RUN}/tasks/1/attempt-1/diff.patch", f"run:{RUN}/plan.json", "other:x/y.md"])
def test_bad_ids_refused(folder, bad):
    with pytest.raises(common.OpsError):
        docs.show(bad)


def test_missing_things_are_not_found(folder):
    with pytest.raises(common.NotFound):
        docs.show(f"run:{RUN}/nope.md")
    with pytest.raises(common.NotFound):
        docs.show("run:20200101-000000-none/plan.md")
    with pytest.raises(common.NotFound):
        docs.show("notes:ghost/idea.md")


def test_symlink_out_refused(folder, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("# outside\n")
    os.symlink(outside, folder / "link.md")
    os.symlink(tmp_path, folder / "dir")
    with pytest.raises(common.OpsError):
        docs.show(f"run:{RUN}/link.md")
    with pytest.raises(common.OpsError):
        docs.show(f"run:{RUN}/dir/secret.md")
    assert not any("link.md" in r["id"] or "dir/" in r["id"] for r in docs.list(RUN))


def test_text_is_scrubbed(folder):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (folder / "summary.md").write_text("# Summary\nthe key is sekrit-value-12345 ok\n")
    assert "sekrit-value-12345" not in docs.show(f"run:{RUN}/summary.md")["text"]
    assert "sekrit-value-12345" not in repr(docs.list(RUN))


def test_api_list_show_download(api, folder):
    status, body = api(f"/api/docs/list?run={RUN}")
    assert status == 200 and body["data"][0]["id"] == f"run:{RUN}/plan.md"
    status, body = api(f"/api/docs/show?id=run:{RUN}/plan.md")
    assert status == 200 and body["data"]["title"] == "The plan"
    status, body = api(f"/api/docs/show?id=run:{RUN}/../x.md")
    assert status == 400 and not body["ok"]
    assert api(f"/api/docs/show?id=run:{RUN}/gone.md")[0] == 404
    assert api("/api/docs/list?run=bad")[0] == 400


def test_api_download_headers(api, folder):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (folder / "summary.md").write_text("# S\nsekrit-value-12345\n")
    status, resp, content = api(f"/api/docs/download?id=run:{RUN}/summary.md", raw=True)
    assert status == 200
    assert resp.headers["Content-Disposition"] == 'attachment; filename="summary.md"'
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert b"sekrit-value-12345" not in content and b"# S" in content
    assert api(f"/api/docs/download?id=run:{RUN}/../x.md")[0] == 400


def test_download_file_name_is_safe(folder):
    (folder / "we ird\";x.md").write_text("hi")
    name = docs.download(f"run:{RUN}/we ird\";x.md")["name"]
    assert name == "we_ird__x.md"


def test_cli_show_and_list(folder, capsys):
    assert main(["doc", "show", f"run:{RUN}/plan.md"]) == 0
    assert capsys.readouterr().out.startswith("# The plan")
    assert main(["doc", "list", RUN]) == 0
    assert f"run:{RUN}/plan.md" in capsys.readouterr().out
    assert main(["doc", "list", RUN, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["title"] == "The plan"
    assert main(["doc", "show", f"run:{RUN}/../x.md"]) != 0


def test_gate_links_carry_doc_ids():
    from steps.planner import run as planner
    import inspect
    assert '"doc": f"run:{ctx.run.id}/plan.md"' in inspect.getsource(planner)


def _swap_on_open(monkeypatch, folder, outside, name):
    """Swap folder/<name> for a symlink to <outside> the moment the document is opened (a TOCTOU race won)."""
    real_os_open, real_open = os.open, open

    def swap(path):
        p = str(path)
        if p.endswith(f"{name}/doc.md") and (folder / name).is_dir() and not (folder / name).is_symlink():
            (folder / name).rename(folder / f"{name}-old")
            os.symlink(outside, folder / name)

    def os_open(path, *a, **k):
        swap(path)
        return real_os_open(path, *a, **k)

    def py_open(path, *a, **k):
        swap(path)
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(docs, "open", py_open, raising=False)


def test_symlink_swap_after_check_is_refused(folder, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "doc.md").write_text("# stolen\nTOP SECRET\n")
    (folder / "sub").mkdir()
    (folder / "sub" / "doc.md").write_text("# fine\n")
    _swap_on_open(monkeypatch, folder, outside, "sub")
    with pytest.raises(common.OpsError) as err:
        docs.show(f"run:{RUN}/sub/doc.md")
    assert "TOP SECRET" not in str(err.value)


def test_unreadable_or_vanished_is_not_found(folder, monkeypatch):
    def gone(*a, **k):
        raise FileNotFoundError("vanished")
    monkeypatch.setattr(os, "open", gone)
    monkeypatch.setattr(docs, "open", gone, raising=False)
    with pytest.raises(common.NotFound):
        docs.show(f"run:{RUN}/plan.md")


def test_fifo_and_folders_are_not_found(folder):
    os.mkfifo(folder / "pipe.md")
    (folder / "adir.md").mkdir()
    with pytest.raises(common.NotFound):
        docs.show(f"run:{RUN}/pipe.md")
    with pytest.raises(common.NotFound):
        docs.show(f"run:{RUN}/adir.md")


def test_list_reads_only_the_start_of_each_file(folder, monkeypatch):
    (folder / "big.md").write_text("# Big one\n" + "x" * 2_000_000)
    limits = []
    real = docs._read_fd
    monkeypatch.setattr(docs, "_read_fd", lambda fd, limit: limits.append(limit) or real(fd, limit))
    rows = {r["id"]: r for r in docs.list(RUN)}
    assert rows[f"run:{RUN}/big.md"]["title"] == "Big one"
    assert rows[f"run:{RUN}/big.md"]["size"] > 2_000_000
    assert limits and max(limits) <= docs.TITLE_BYTES == 4096


def test_list_title_never_uses_a_cut_line(folder):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (folder / "cut.md").write_text("x" * 4080 + "\n# sekrit-value-12345\n")
    row = next(r for r in docs.list(RUN) if r["id"].endswith("cut.md"))
    assert row["title"] == "cut.md" and "sekrit" not in repr(row)
