"""Tests for secret scrubbing."""
from phoenix9 import scrub
from phoenix9.scrub import Scrubber, read_env_file


def test_short_values_ignored():
    """Values under 8 characters are never scrubbed."""
    assert Scrubber(["short", "1234567"]).text("short 1234567") == "short 1234567"


def test_replaces_and_multiline():
    """Every occurrence on every line is replaced."""
    s = Scrubber(["supersecret1"])
    assert s.text("a supersecret1\nb supersecret1 c") == "a [secret]\nb [secret] c"


def test_overlapping_longest_first():
    """A longer secret containing a shorter one is replaced whole."""
    s = Scrubber(["abcdefgh", "abcdefghij"])
    assert s.text("x abcdefghij y") == "x [secret] y"
    s.add(["zzzzzzzz"])
    assert s.text("zzzzzzzz abcdefgh") == "[secret] [secret]"


def test_json_escaped_form():
    """A secret with a quote is also found inside JSON text."""
    s = Scrubber(['pa"ss12345'])
    assert s.text('{"k": "pa\\"ss12345"}') == '{"k": "[secret]"}'


def test_env_file_parsing(tmp_path):
    """Quotes, comments, export and blank lines are handled."""
    f = tmp_path / "a.env"
    f.write_text('# c\n\nA=plainvalue1\nexport B="quoted value"\nC=\'single one\'\nbad line\nD=x\n')
    assert read_env_file(f) == {"A": "plainvalue1", "B": "quoted value", "C": "single one", "D": "x"}
    s = Scrubber.from_env_files([f, tmp_path / "missing.env"])
    assert s.text("plainvalue1 quoted value single one x") == "[secret] [secret] [secret] x"


def test_module_helper():
    """The shared helper scrubs what add_secrets registered."""
    scrub.add_secrets(["globalsecret"])
    assert scrub.scrub("a globalsecret") == "a [secret]"
