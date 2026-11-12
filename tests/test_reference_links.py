"""Reference links: parsing, notes, de-duplication, refusals, removal."""
import pytest

from phoenix9 import paths, reference
from phoenix9.reference import ReferenceError_


@pytest.fixture
def proj():
    (paths.projects() / "demo").mkdir()
    return "demo"


def test_parse_with_notes_comments_and_order(proj):
    text = "# my links\n\nhttps://b.example.com/x | copy the colours\nhttp://a.example.com\n"
    got = reference.add_links(proj, text, "alex")
    assert [a["url"] for a in got["added"]] == ["https://b.example.com/x", "http://a.example.com"]
    assert reference.list_links(proj) == [
        {"url": "https://b.example.com/x", "note": "copy the colours"},
        {"url": "http://a.example.com", "note": ""}]


def test_duplicates_and_append(proj):
    reference.add_links(proj, "https://a.example.com\nhttps://a.example.com | x", "alex")
    got = reference.add_links(proj, "https://a.example.com\nhttps://c.example.com", "alex")
    assert got["skipped"] == 1
    assert [l["url"] for l in reference.list_links(proj)] == ["https://a.example.com", "https://c.example.com"]


def test_note_cleaned(proj):
    reference.add_links(proj, "https://a.example.com | hi\x07 there " + "z" * 300, "alex")
    note = reference.list_links(proj)[0]["note"]
    assert "\x07" not in note and len(note) <= 200


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "ftp://a.example.com/x",
    "https://user:pw@a.example.com", "http://localhost:3000", "http://127.0.0.1/", "http://10.1.2.3",
    "http://192.168.1.1", "http://169.254.169.254/latest", "http://db.internal/", "http://printer.local/",
    "http://[::1]/", "https://a.example.com/" + "x" * 500,
])
def test_refused(proj, bad):
    with pytest.raises(ReferenceError_):
        reference.add_links(proj, "https://ok.example.com\n" + bad, "alex")
    assert reference.list_links(proj) == []


def test_too_many(proj):
    text = "\n".join(f"https://e.example.com/{i}" for i in range(101))
    with pytest.raises(ReferenceError_):
        reference.add_links(proj, text, "alex")
    reference.add_links(proj, text.rsplit("\n", 1)[0], "alex")
    assert len(reference.list_links(proj)) == 100


def test_no_links_found(proj):
    with pytest.raises(ReferenceError_):
        reference.add_links(proj, "just words\n", "alex")


def test_remove(proj):
    reference.add_links(proj, "https://a.example.com\nhttps://b.example.com", "alex")
    reference.remove_link(proj, "https://a.example.com")
    assert [l["url"] for l in reference.list_links(proj)] == ["https://b.example.com"]
    with pytest.raises(ReferenceError_):
        reference.remove_link(proj, "https://a.example.com")


def test_txt_upload_stays_a_file_and_import(proj):
    data = b"https://a.example.com | note\n"
    reference.add_file(proj, "urls.txt", data, "alex")
    assert reference.list_links(proj) == []
    got = reference.import_links_file(proj, data, "alex")
    assert got["links"] == [{"url": "https://a.example.com", "note": "note"}]
    with pytest.raises(ReferenceError_):
        reference.import_links_file(proj, b"\xff\xfe", "alex")
