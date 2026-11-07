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


# ---- pattern masks: secrets nobody told the scrubber about ----
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FAKE_ANT = "sk-ant-api03-" + "Ab1_" * 12
FAKE_GHP = "ghp_" + "a1B2c3D4e5" * 4
FAKE_GHS = "ghs_" + "Z9y8X7w6V5" * 4
FAKE_PAT = "github_pat_" + "11ABCDEFG0" * 3 + "_" + "q" * 40
PEM = ("-----BEGIN OPENSSH PRIVATE KEY-----\n" + ("b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAA\n" * 4)
       + "-----END OPENSSH PRIVATE KEY-----")


@pytest.mark.parametrize("secret", [FAKE_ANT, FAKE_GHP, FAKE_GHS, FAKE_PAT, PEM])
def test_known_token_shapes_are_masked_without_being_registered(secret):
    out = scrub.scrub("before %s after" % secret)
    assert secret not in out and "[secret]" in out and out.startswith("before ") and out.endswith(" after")


def test_pem_tail_without_its_begin_line_is_masked():
    """A last-6-lines excerpt can hold only the end of a key."""
    tail = "\n".join(PEM.splitlines()[-3:])
    out = scrub.scrub(tail)
    assert "b3BlbnNzaC1rZXkt" not in out


@pytest.mark.parametrize("line,keep", [
    ("ANTHROPIC_API_KEY=abc123def456", "ANTHROPIC_API_KEY="),
    ("export GH_TOKEN='tok-value-99'", "GH_TOKEN="),
    ('DB_PASSWORD="hunter2hunter2"', "DB_PASSWORD="),
    ("client_secret = s3cr3tvalue", "client_secret"),
])
def test_assignments_of_secret_names_are_masked(line, keep):
    out = scrub.scrub(line)
    assert keep in out and "[secret]" in out
    value = line.split("=", 1)[1].strip().strip("'\"")
    assert value not in out


@pytest.mark.parametrize("name", ["API_KEY", "apiKey", "APIKey", "GITHUB_TOKEN", "db-password", "client.secret",
                                  "AWS_SECRET_ACCESS_KEY", "X-Api-Key", "authToken", "apikey", "access_token",
                                  "KEY", "key2", "MY_KEYS", "db_passwd", "privateKey", "SERVICE_ROLE_SECRET"])
def test_secret_words_count_as_whole_parts_of_the_name(name):
    out = scrub.scrub(f"{name}=value-1234567")
    assert out.startswith(name) and "[secret]" in out and "value-1234567" not in out


@pytest.mark.parametrize("name", ["monkey", "turkey", "keyboard", "donkey_kong", "Hockey", "tokenizer",
                                  "secretary", "passwordless", "keynote", "whiskey.brand", "monkeyPatch"])
def test_names_that_only_contain_a_secret_word_are_left_alone(name):
    line = f"{name}=banana-split-42"
    assert scrub.scrub(line) == line


def test_name_parts_split_on_separators_and_case_changes():
    assert scrub.name_parts("AWS_SECRET-access.Key") == ["aws", "secret", "access", "key"]
    assert scrub.name_parts("myAPIKey2") == ["my", "api", "key", "2"]
    assert scrub.name_parts("monkey") == ["monkey"]


def test_ordinary_text_is_left_alone():
    text = "ran ls -la; KEY= (empty); token count 42; skip=ant; the secret garden"
    assert scrub.scrub(text) == text


def test_fresh_cli_process_loads_phoenix_secrets(tmp_path):
    """A brand-new phoenix process (nothing preloaded) scrubs saved global secrets and project keys."""
    from phoenix9 import keys, paths
    (paths.projects() / "alpha").mkdir()
    (paths.projects() / "alpha" / "CLAUDE.md").write_text("# alpha\n")
    keys.set_key("alpha", "STRIPE_KEY", "rk_live_project_value_77", True)
    keys.write_secret_file("service-supabase.env", {"SUPABASE_ACCESS_TOKEN": "sbp_global_value_88"})
    line = json.dumps({"type": "user", "message": {"content": "pasted rk_live_project_value_77 and sbp_global_value_88"}})
    code = ("import io, contextlib, json, sys\n"
            "from phoenix9 import scrub, transcript\n"
            "assert not scrub.known_secrets()\n"
            "from phoenix9.__main__ import main\n"
            "with contextlib.redirect_stdout(io.StringIO()):\n"
            "    main([])\n"
            "print(json.dumps(transcript.parse([sys.argv[1]])[0]))\n")
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code, line], capture_output=True, text=True, cwd=root,
                         env={**os.environ}, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "rk_live_project_value_77" not in out.stdout and "sbp_global_value_88" not in out.stdout
    assert out.stdout.count("[secret]") == 2


def test_api_server_loads_phoenix_secrets(monkeypatch):
    """make_server teaches the scrubber the saved secrets too (the API may be started without the CLI)."""
    from phoenix9 import keys
    from phoenix9.api import server
    keys.write_secret_file("service-x.env", {"X_TOKEN": "api_global_value_99"})
    monkeypatch.setattr(scrub, "_GLOBAL", scrub.Scrubber())
    httpd = server.make_server(0)
    httpd.server_close()
    assert scrub.scrub("api_global_value_99") == "[secret]"


def test_pattern_masks_stay_fast_on_big_text():
    """Long runs of dotted words, KEY-ish text or base64 lines must not make scrubbing slow (no backtracking)."""
    import base64
    import time
    cases = [".".join("abc-def" for _ in range(30000)), "KEY_" * 50000, "x" * 300000,
             "aB" * 150000 + "=value-12345", ("monkeyKEYmonkey=banana-split " * 10000),
             "\n".join(base64.b64encode(os.urandom(57)).decode() for _ in range(5000)) + "\n-----END PRIVATE KEY-----"]
    for text in cases:
        t0 = time.monotonic()
        scrub.scrub(text)
        assert time.monotonic() - t0 < 1.0
