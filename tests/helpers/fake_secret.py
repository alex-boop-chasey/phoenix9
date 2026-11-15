"""Fake key-shaped strings for tests, built at run time from pieces.

Why: a test file that holds a key-shaped string literally (a live Stripe key, a private key block, an AWS,
GitHub or Anthropic key) makes Phoenix's own secret scan (`phoenix9/git.py` SECRET_PATTERNS) refuse the
commit, and teaches builders to write such strings. So tests call `fake_secret(kind)` instead; the pieces
in this file never match a pattern on their own. `tests/test_no_literal_secrets.py` guards the rule.
"""

import hashlib

UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = UPPER.lower()
DIGITS = "0123456789"
ALNUM = UPPER + LOWER + DIGITS
B64 = ALNUM + "+/"


def _body(kind: str, seed: str, length: int, alphabet: str = ALNUM) -> str:
    """A random-looking run of `length` characters from `alphabet`, the same for the same kind and seed."""
    out, n = [], 0
    while len(out) < length:
        digest = hashlib.sha256(f"{kind}:{seed}:{n}".encode()).digest()
        out.extend(alphabet[b % len(alphabet)] for b in digest)
        n += 1
    return "".join(out[:length])


def _pem(seed: str) -> str:
    """A full RSA private key block (BEGIN line, four base64 lines, END line)."""
    lines = [_body("private_key", f"{seed}:{i}", 64, B64) for i in range(4)]
    return ("-----BEGIN " + "RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n"
            + "-----END " + "RSA PRIVATE KEY-----")


BUILDERS = {
    "stripe_live": lambda seed: "sk" + "_live_" + _body("stripe_live", seed, 24),
    "private_key": _pem,
    "aws": lambda seed: "AK" + "IA" + _body("aws", seed, 16, UPPER + DIGITS),
    "github": lambda seed: "gh" + "p_" + _body("github", seed, 36),
    "github_pat": lambda seed: ("github" + "_pat_" + _body("github_pat", seed, 22) + "_"
                                + _body("github_pat", seed + ":2", 59)),
    "anthropic": lambda seed: "sk-" + "ant-" + "api03-" + _body("anthropic", seed, 40),
    "generic": lambda seed: _body("generic", seed, 48),
}
KINDS = tuple(BUILDERS)


def fake_secret(kind: str, seed: str = "a") -> str:
    """A fake secret of the given kind (see KINDS); a different seed gives a different value."""
    if kind not in BUILDERS:
        raise ValueError(f"unknown fake secret kind {kind!r}; use one of {', '.join(KINDS)}")
    return BUILDERS[kind](seed)
