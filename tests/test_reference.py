"""Reference storage: add, list, remove and every refusal."""
import os

import pytest

from phoenix9 import paths, reference
from phoenix9.reference import ReferenceError_

PNG = b"\x89PNG\r\n\x1a\n\x00\x00"


@pytest.fixture
def proj():
    (paths.projects() / "demo").mkdir()
    return "demo"


def ref_dir():
    return paths.projects() / "demo" / "notes" / "reference"


def test_add_list_remove(proj):
    assert reference.list_files(proj) == []
    reference.add_file(proj, "b.css", b"a{}", "alex")
    reference.add_file(proj, "a.png", PNG, "alex")
    reference.add_file(proj, "tokens.json", b"{}", "alex")
    got = reference.list_files(proj)
    assert [f["name"] for f in got] == ["a.png", "b.css", "tokens.json"]
    assert [f["kind"] for f in got] == ["image", "style", "design tokens"]
    assert got[1]["size"] == 3 and got[1]["modified"].endswith("Z")
    reference.remove_file(proj, "b.css")
    assert [f["name"] for f in reference.list_files(proj)] == ["a.png", "tokens.json"]
    with pytest.raises(ReferenceError_):
        reference.remove_file(proj, "b.css")
    with pytest.raises(ReferenceError_):
        reference.remove_file(proj, "../x")


def test_links_kind_and_hidden_skipped(proj):
    reference.add_file(proj, "links.txt", b"https://example.com\n", "alex")
    (ref_dir() / ".hidden").write_text("x")
    (ref_dir() / "sub").mkdir()
    assert [(f["name"], f["kind"]) for f in reference.list_files(proj)] == [("links.txt", "links")]


@pytest.mark.parametrize("name", [".env", "key.pem", "run.sh", "a.zip", "noext", "x.py", "id_rsa"])
def test_disallowed_types(proj, name):
    with pytest.raises(ReferenceError_) as e:
        reference.add_file(proj, name, b"hello", "alex")
    assert ".css" in str(e.value)


def test_name_cleaning(proj):
    assert reference.add_file(proj, "../../My Style!.CSS", b"a{}", "a")["name"] == "My-Style.css"
    assert reference.add_file(proj, "..a..b.txt", b"x", "a")["name"] == "a.b.txt"
    long = reference.add_file(proj, "n" * 300 + ".md", b"x", "a")["name"]
    assert len(long) == 100 and long.endswith(".md")
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, ".css", b"x", "a")
    assert not (paths.projects() / "demo" / "My-Style.css").exists()


def test_clash_suffix_and_replace(proj):
    reference.add_file(proj, "a.txt", b"one", "a")
    assert reference.add_file(proj, "a.txt", b"two", "a")["name"] == "a-2.txt"
    assert reference.add_file(proj, "a.txt", b"three", "a", replace=True)["name"] == "a.txt"
    assert (ref_dir() / "a.txt").read_bytes() == b"three"
    assert len(reference.list_files(proj)) == 2


def test_size_limits(proj, monkeypatch):
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "big.txt", b"x" * (reference.MAX_FILE + 1), "a")
    monkeypatch.setattr(reference, "MAX_FILES", 2)
    reference.add_file(proj, "1.txt", b"x", "a")
    reference.add_file(proj, "2.txt", b"x", "a")
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "3.txt", b"x", "a")
    reference.add_file(proj, "2.txt", b"y", "a", replace=True)      # replacing does not add a file


def test_total_limit(proj, monkeypatch):
    monkeypatch.setattr(reference, "MAX_TOTAL", 10)
    reference.add_file(proj, "1.txt", b"x" * 6, "a")
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "2.txt", b"x" * 6, "a")
    reference.add_file(proj, "1.txt", b"x" * 9, "a", replace=True)


def test_binary_behind_text_extension(proj):
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "a.css", b"\xff\xfe\x00\x01", "a")
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "a.txt", b"ab\x00cd", "a")
    reference.add_file(proj, "a.png", b"\xff\xfe\x00\x01", "a")     # images are binary on purpose


def test_secret_refused(proj):
    for text in (b"token sk-ant-abcdefgh12345678", b"API_KEY=abcdef123456",
                 b"-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"):
        with pytest.raises(ReferenceError_) as e:
            reference.add_file(proj, "n.md", text, "a")
        assert "key manager" in str(e.value)
        assert "abcdef123456" not in str(e.value)
    assert reference.list_files(proj) == []


def test_empty_refused(proj):
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "a.txt", b"", "a")


def test_atomic_write_leaves_no_temp_files(proj, monkeypatch):
    reference.add_file(proj, "a.txt", b"one", "a")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            reference.add_file(proj, "a.txt", b"two", "a", replace=True)
    assert sorted(p.name for p in ref_dir().iterdir()) == ["a.txt"]
    assert (ref_dir() / "a.txt").read_bytes() == b"one"


def test_symlinks(proj, tmp_path):
    reference.add_file(proj, "a.txt", b"x", "a")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (ref_dir() / "link.txt").symlink_to(outside)
    assert [f["name"] for f in reference.list_files(proj)] == ["a.txt"]
    with pytest.raises(ReferenceError_):
        reference.remove_file(proj, "link.txt")
    assert reference.add_file(proj, "link.txt", b"y", "a")["name"] == "link-2.txt"
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "link.txt", b"y", "a", replace=True)
    assert outside.read_text() == "secret"


def test_symlinked_folder_refused(proj, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (paths.projects() / "demo" / "notes").mkdir()
    ref_dir().symlink_to(target)
    with pytest.raises(ReferenceError_):
        reference.add_file(proj, "a.txt", b"x", "a")
    assert list(target.iterdir()) == []
