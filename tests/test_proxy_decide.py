"""Key proxy: the pure decision functions (matcher, path safety, decide, headers, redaction), no sockets."""
import email.message
import itertools
import random

import pytest

from phoenix9 import proxy
from phoenix9.proxy import ProxySpec

TOKEN = "t" * 43
KEY = "sk-SENTINEL-123"


def headers(**kv):
    """A header block like the one the HTTP server hands the handler."""
    m = email.message.Message()
    for k, v in kv.items():
        m[k.replace("_", "-")] = v
    return m


def spec(*rules):
    """A spec with the given (method, path) rules."""
    return ProxySpec("svc", "https://api.example.com", "Authorization", "Bearer {key}",
                     tuple(proxy.parse_rules([{"method": m, "path": p} for m, p in rules])))


def decide(s, method, target, hdrs=None, max_body=100):
    """decide() with the token header filled in unless hdrs is given."""
    hdrs = hdrs if hdrs is not None else headers(**{"X_Phoenix_Proxy_Token": TOKEN})
    return proxy.decide(s, TOKEN, method, target, hdrs, max_body=max_body)


SEGMENTS = ["a", "b", "v1", "projects", "x-y", "%61", "_", "1"]


def random_path(rng, n):
    """A safe path of n segments."""
    return "/" + "/".join(rng.choice(SEGMENTS) for _ in range(n))


def test_matcher_literal_only_matches_itself():
    rng = random.Random(1)
    for _ in range(300):
        a, b = random_path(rng, rng.randint(1, 4)), random_path(rng, rng.randint(1, 4))
        assert proxy.pattern_matches(a, b) == (a == b)


def test_matcher_star_is_exactly_one_segment():
    rng = random.Random(2)
    for _ in range(300):
        n = rng.randint(1, 4)
        path = random_path(rng, n)
        parts = path.split("/")[1:]
        i = rng.randrange(n)
        pattern = "/" + "/".join("*" if j == i else p for j, p in enumerate(parts))
        assert proxy.pattern_matches(pattern, path)
        assert not proxy.pattern_matches(pattern, path + "/extra")
        assert not proxy.pattern_matches(pattern, "/" + "/".join(parts[:i] + [""] + parts[i + 1:]))
        if n > 1:
            assert not proxy.pattern_matches(pattern, "/" + "/".join(parts[:i] + parts[i + 1:]))


def test_matcher_double_star_is_one_or_more_trailing_segments():
    rng = random.Random(3)
    for _ in range(300):
        head = random_path(rng, rng.randint(1, 3))
        assert not proxy.pattern_matches(head + "/**", head)
        for extra in range(1, 4):
            assert proxy.pattern_matches(head + "/**", head + random_path(rng, extra))
        assert not proxy.pattern_matches(head + "/**", head + "/")
        assert not proxy.pattern_matches(head + "/**", head + "/a//b")


def test_matcher_is_case_sensitive():
    assert not proxy.pattern_matches("/v1/projects", "/V1/projects")


SAFE = ["/v1/projects", "/repos/o/r/git/refs/tags/v1.2", "/a/%61", "/a/b.c", "/a/...", "/a/%20x", "/a/~u"]
UNSAFE = ["/v1/../admin", "/v1/%2e%2e/admin", "/v1/%2E%2E/admin", "/v1//x", "/v1/%2F/x", "/v1/%2f/x",
          "/v1\\x", "/v1/%5c", "/v1/%5C", "/v1/%00", "/v1/./x", "/v1/.", "/v1/..", "//x", "/a/%252e%252e",
          "/a/%252f", "/a/%09", "/a/\x01", "/a/\x7f", "/a#b", "/a/%ff", "x/a", "", "*",
          "/a;b", "/a/b;c", "/a/\u00e9", "/a b", "/a\"b", "/a<b>", "/a/^", "/a/`", "/a/|", "/a/{b}"]


@pytest.mark.parametrize("path", SAFE)
def test_safe_paths(path):
    assert proxy.path_is_safe(path)


@pytest.mark.parametrize("path", UNSAFE)
def test_unsafe_paths(path):
    assert not proxy.path_is_safe(path)


def test_any_dot_segment_anywhere_is_unsafe():
    for parts in itertools.product(["a", "..", ".", "%2e", "%2E%2e"], repeat=3):
        path = "/" + "/".join(parts)
        unsafe = any(p != "a" for p in parts)
        assert proxy.path_is_safe(path) is not unsafe, path


def test_decide_order_token_first():
    s = spec(("GET", "/a"))
    assert decide(s, "GET", "/a", headers()).status == 401
    assert decide(s, "CONNECT", "x:443", headers()).status == 401
    wrong = headers(**{"X_Phoenix_Proxy_Token": "nope"})
    assert decide(s, "GET", "/a", wrong).reason == "bad token"


@pytest.mark.parametrize("method,target,status,reason", [
    ("GET", "/a", 200, ""),
    ("GET", "/a?x=1", 200, ""),
    ("HEAD", "/a", 403, "not a declared call"),
    ("DELETE", "/a", 403, "not a declared call"),
    ("CONNECT", "evil:443", 405, "method CONNECT not allowed"),
    ("OPTIONS", "*", 405, "method OPTIONS not allowed"),
    ("TRACE", "/a", 405, "method TRACE not allowed"),
    ("get", "/a", 405, "method get not allowed"),
    ("GET", "http://evil/a", 403, "not an origin-form path"),
    ("GET", "/a/../a", 403, "unsafe path"),
    ("GET", "/b", 403, "not a declared call"),
    ("GET", "/a?x=\x01", 403, "unsafe path"),
    ("GET", "/a?x=\x7f", 403, "unsafe path"),
])
def test_decide_table(method, target, status, reason):
    d = decide(spec(("GET", "/a")), method, target)
    assert (d.status, d.reason, d.allowed) == (status, reason, status == 200)


def test_decide_splits_query_and_checks_path_without_it():
    d = decide(spec(("GET", "/a")), "GET", "/a?next=/../x")
    assert d.allowed and d.path == "/a" and d.query == "?next=/../x"


def test_decide_body_rules():
    s = spec(("POST", "/a"))
    tok = {"X_Phoenix_Proxy_Token": TOKEN}
    assert decide(s, "POST", "/a", headers(**tok, Content_Length="100")).body_length == 100
    assert decide(s, "POST", "/a", headers(**tok, Content_Length="101")).status == 413
    assert decide(s, "POST", "/a", headers(**tok, Transfer_Encoding="chunked")).status == 411
    assert decide(s, "POST", "/a", headers(**tok, Content_Length="-1")).status == 400
    two = headers(**tok, Content_Length="1")
    two["Content-Length"] = "2"
    assert decide(s, "POST", "/a", two).status == 400


def test_outgoing_headers_drop_and_set():
    s = ProxySpec("svc", "https://x", "Authorization", "Bearer {key}", (),
                  extra_headers=(("X-GitHub-Api-Version", "2022-11-28"),))
    caller = [("Authorization", "Bearer evil"), ("authorization", "x"), ("Cookie", "c"), ("Host", "evil"),
              ("X-Phoenix-Proxy-Token", TOKEN), ("Proxy-Authorization", "p"), ("Connection", "X-Hop"),
              ("X-Hop", "1"), ("Content-Length", "5"), ("Transfer-Encoding", "chunked"),
              ("Accept-Encoding", "gzip"), ("x-github-api-version", "old"), ("Content-Type", "a/b")]
    out = proxy.outgoing_headers(s, KEY, caller)
    assert out == [("Content-Type", "a/b"), ("Authorization", f"Bearer {KEY}"),
                   ("X-GitHub-Api-Version", "2022-11-28"), ("Accept-Encoding", "identity")]


def test_redact_all_key_forms():
    import base64
    data = (KEY.encode() + b" " + base64.b64encode(KEY.encode()) + b" "
            + base64.urlsafe_b64encode(KEY.encode()).rstrip(b"="))
    out = proxy.redact(data, KEY)
    assert out == b"[redacted] [redacted] [redacted]"
