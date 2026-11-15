"""No test file holds a key-shaped string literally; fake ones come from `helpers.fake_secret`."""

from pathlib import Path

import pytest

from helpers.fake_secret import KINDS, fake_secret
from phoenix9 import git, scrub

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("tests", "agentkit/tests")
HELPER = ROOT / "tests" / "helpers" / "fake_secret.py"

# which secret-scan pattern (by its words) each kind imitates; generic imitates none
GIT_PATTERN = {
    "stripe_live": "Stripe", "private_key": "private key", "aws": "AWS", "github": "GitHub",
    "github_pat": "GitHub", "anthropic": "Anthropic",
}


def _test_files():
    """Every Python file under the scanned test folders, except the helper's own pieces."""
    for folder in SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if path != HELPER and ".venv" not in path.parts:
                yield path


def test_no_test_file_holds_a_literal_secret():
    found = []
    for path in _test_files():
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for rx, what in git.SECRET_PATTERNS:
                if rx.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {what}")
    assert not found, ("These test lines hold a key-shaped string, which makes the secret scan refuse the "
                       "commit; build it with fake_secret(kind) from tests/helpers/fake_secret.py:\n"
                       + "\n".join(found))


def test_the_helper_itself_holds_no_literal_secret():
    text = HELPER.read_text()
    assert not [what for rx, what in git.SECRET_PATTERNS if rx.search(text)]


@pytest.mark.parametrize("kind", sorted(GIT_PATTERN))
def test_each_kind_matches_the_pattern_it_imitates(kind):
    value = fake_secret(kind)
    matched = [what for rx, what in git.SECRET_PATTERNS if rx.search(value)]
    assert len(matched) == 1 and GIT_PATTERN[kind] in matched[0]
    assert git.scan_secrets(f"diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+v = {value}\n")


@pytest.mark.parametrize("kind", ["private_key", "github", "github_pat", "anthropic"])
def test_kinds_scrub_knows_are_masked(kind):
    value = fake_secret(kind)
    assert any(rx.search(value) for rx, _ in scrub.PATTERNS)
    out = scrub.scrub(f"before {value} after")
    assert value not in out and "[secret]" in out


def test_private_key_is_a_full_block():
    lines = fake_secret("private_key").splitlines()
    assert lines[0] == "-----BEGIN " + "RSA PRIVATE KEY-----" and lines[-1] == "-----END " + "RSA PRIVATE KEY-----"
    assert len(lines) >= 3


def test_generic_is_long_random_looking_and_matches_no_shape():
    value = fake_secret("generic")
    assert len(value) >= 32 and value.isalnum() and len(set(value)) > 16
    assert not any(rx.search(value) for rx, _ in git.SECRET_PATTERNS)
    assert value not in scrub.scrub(f"API_KEY={value}")


def test_seeds_give_different_values_and_unknown_kinds_are_refused():
    for kind in KINDS:
        assert fake_secret(kind) == fake_secret(kind, "a") != fake_secret(kind, "b")
    with pytest.raises(ValueError):
        fake_secret("nope")
