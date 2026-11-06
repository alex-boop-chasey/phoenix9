"""Key proxy: the acceptance scenarios, against a real local upstream on 127.0.0.1."""
import base64
import http.client
import json
import os
import socket
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from phoenix9 import proxy
from phoenix9.proxy import ProxySpec, Rule

KEY = "sk-SENTINEL-123"


class Upstream:
    """A real HTTP server on 127.0.0.1:0 that records every request and answers with a switchable reply."""

    def __init__(self):
        """Start serving with a plain 200 reply."""
        self.requests: list[dict] = []
        self.reply = {"status": 200, "headers": {}, "body": b"ok", "echo": False, "sleep": 0.0}
        outer = self

        class H(BaseHTTPRequestHandler):
            def _any(self):
                path, _, query = self.path.partition("?")
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.requests.append({"method": self.command, "path": path, "query": query,
                                       "headers": dict(self.headers.items()), "body": body})
                r = outer.reply
                if r["sleep"]:
                    time.sleep(r["sleep"])
                data = r["body"]
                if r["echo"]:
                    data = json.dumps(dict(self.headers.items())).encode()
                self.send_response(r["status"])
                pairs = r["headers"].items() if isinstance(r["headers"], dict) else r["headers"]
                for k, v in pairs:   # a list of pairs can repeat a header
                    self.send_header(k, v)
                if r["echo"]:
                    self.send_header("X-Echo-Auth", self.headers.get("Authorization", ""))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _any

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()

    def close(self):
        """Stop the test server."""
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream():
    """A recording upstream server."""
    u = Upstream()
    yield u
    u.close()


@pytest.fixture
def upstream2():
    """A second recording upstream server."""
    u = Upstream()
    yield u
    u.close()


def make_spec(upstream_url, rules=None):
    """A Supabase-like spec pointing at the test upstream."""
    rules = rules or [{"method": "GET", "path": "/v1/projects"}]
    return ProxySpec(service="supabase", upstream=upstream_url, auth_header="Authorization",
                     auth_format="Bearer {key}", rules=tuple(proxy.parse_rules(rules)))


@pytest.fixture
def log_path(tmp_path):
    """Where the proxy log goes."""
    return tmp_path / "run" / "logs" / "proxy-supabase.jsonl"


def start(upstream_url, log_path, rules=None, **kw):
    """Start a proxy on a test upstream (plain http allowed for loopback)."""
    return proxy.serve(make_spec(upstream_url, rules), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True, **kw)


def call(p, method, target, headers=None, body=None, token=True):
    """Send one request to the proxy; returns (status, headers dict, body)."""
    conn = http.client.HTTPConnection("127.0.0.1", p.port, timeout=10)
    h = dict(headers or {})
    if token:
        h[proxy.TOKEN_HEADER] = p.token if token is True else token
    conn.request(method, target, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), data


def raw(p, data: bytes) -> bytes:
    """Send raw bytes to the proxy and return what comes back."""
    with socket.create_connection(("127.0.0.1", p.port), timeout=10) as s:
        s.sendall(data)
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out


def log_lines(path):
    """Every log line as a dict."""
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_declared_call_forwarded_with_key_added(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, body = call(p, "GET", "/v1/projects?limit=5&x=a%20b")
    assert status == 200 and body == b"ok"
    [req] = upstream.requests
    assert req["headers"]["Authorization"] == "Bearer sk-SENTINEL-123"
    assert req["path"] == "/v1/projects" and req["query"] == "limit=5&x=a%20b"
    assert proxy.TOKEN_HEADER not in req["headers"]
    assert req["headers"]["Host"] == upstream.url.removeprefix("http://")


def test_caller_authorization_is_replaced(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects", headers={"Authorization": "Bearer evil", "Cookie": "a=b"})
    [req] = upstream.requests
    auth = [v for k, v in req["headers"].items() if k.lower() == "authorization"]
    assert auth == ["Bearer sk-SENTINEL-123"]
    assert "Cookie" not in req["headers"]


def test_wildcards(upstream, log_path):
    rules = [{"method": "GET", "path": "/v1/projects/*/api-keys"}, {"method": "GET", "path": "/repos/**"}]
    p = start(upstream.url, log_path, rules)
    try:
        assert call(p, "GET", "/v1/projects/abc/api-keys")[0] == 200
        assert call(p, "GET", "/v1/projects/api-keys")[0] == 403
        assert call(p, "GET", "/v1/projects/a/b/api-keys")[0] == 403
        assert call(p, "GET", "/repos/o/r")[0] == 200
        assert call(p, "GET", "/repos/o/r/git/refs/tags/v1")[0] == 200
        assert call(p, "GET", "/repos")[0] == 403
    finally:
        p.stop()
    assert [r["path"] for r in upstream.requests] == ["/v1/projects/abc/api-keys", "/repos/o/r",
                                                       "/repos/o/r/git/refs/tags/v1"]


def test_undeclared_method_refused_403_and_logged(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, _ = call(p, "DELETE", "/v1/projects")
    assert status == 403 and upstream.requests == []
    [line] = log_lines(log_path)
    assert line["decision"] == "refused" and line["method"] == "DELETE" and line["status"] == 403


def test_undeclared_path_refused_403_and_logged(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, _ = call(p, "GET", "/v1/organizations")
    assert status == 403 and upstream.requests == []
    [line] = log_lines(log_path)
    assert line["decision"] == "refused" and line["path"] == "/v1/organizations"
    assert line["reason"] == "not a declared call"


@pytest.mark.parametrize("target", ["/v1/../admin", "/v1/%2e%2e/admin", "/v1//x", "/v1/%2F/x", "/v1\\x",
                                    "/v1/%00", "/v1/projects/%252e%252e", "/v1/./projects"])
def test_unsafe_paths_refused(upstream, log_path, target):
    rules = [{"method": "GET", "path": "/v1/**"}, {"method": "GET", "path": "/admin"}]
    with proxy.serving(make_spec(upstream.url, rules), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, _ = call(p, "GET", target)
    assert status == 403 and upstream.requests == []
    assert log_lines(log_path)[0]["reason"] == "unsafe path"


def test_absolute_form_and_connect_refused(upstream, log_path):
    rules = [{"method": "GET", "path": "/**"}]
    with proxy.serving(make_spec(upstream.url, rules), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        tok = f"{proxy.TOKEN_HEADER}: {p.token}\r\n".encode()
        absolute = raw(p, b"GET http://evil.example/x HTTP/1.1\r\nHost: evil.example\r\n" + tok + b"\r\n")
        connect = raw(p, b"CONNECT evil.example:443 HTTP/1.1\r\nHost: evil.example\r\n" + tok + b"\r\n")
        options = raw(p, b"OPTIONS * HTTP/1.1\r\n" + tok + b"\r\n")
        trace = raw(p, b"TRACE /x HTTP/1.1\r\n" + tok + b"\r\n")
    assert absolute.split(b" ")[1] == b"403"
    for reply in (connect, options, trace):
        assert reply.split(b" ")[1] in (b"403", b"405")
    assert upstream.requests == []
    assert [line["decision"] for line in log_lines(log_path)] == ["refused"] * 4


def test_missing_or_wrong_token_401(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        assert call(p, "GET", "/v1/projects", token=False)[0] == 401
        assert call(p, "GET", "/v1/projects", token="wrong")[0] == 401
        twice = raw(p, f"GET /v1/projects HTTP/1.1\r\n{proxy.TOKEN_HEADER}: {p.token}\r\n"
                       f"{proxy.TOKEN_HEADER}: {p.token}\r\n\r\n".encode())
        assert twice.split(b" ")[1] == b"401"
    assert upstream.requests == []
    assert {line["reason"] for line in log_lines(log_path)} == {"bad token"}


def test_key_never_in_logs(upstream, log_path, tmp_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects?secret_value=QUERYMARK")
        call(p, "GET", f"/v1/{KEY}?q=QUERYMARK")
        call(p, "DELETE", "/v1/projects")
        call(p, "GET", "/v1/projects", token=False)
        upstream.reply["status"] = 500
        call(p, "GET", "/v1/projects")
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_url = f"http://127.0.0.1:{dead.getsockname()[1]}"
    dead.close()
    with proxy.serving(make_spec(dead_url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects?x=QUERYMARK")
    text = log_path.read_text()
    assert KEY not in text and "QUERYMARK" not in text
    lines = log_lines(log_path)
    assert len(lines) == 6
    for line in lines:
        assert set(line) == {"ts", "service", "step", "method", "path", "query", "decision", "reason",
                             "status", "ms"}
    assert lines[0]["query"] is True and lines[0]["decision"] == "forwarded"
    assert lines[-1]["status"] == 502


def test_key_never_in_responses(upstream, log_path):
    upstream.reply.update(echo=True, headers={"X-Key-B64": base64.b64encode(KEY.encode()).decode()})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, headers, body = call(p, "GET", "/v1/projects")
    assert status == 200
    assert KEY.encode() not in body and b"[redacted]" in body
    assert headers["X-Echo-Auth"] == "Bearer [redacted]"
    assert headers["X-Key-B64"] == "[redacted]"
    assert int(headers["Content-Length"]) == len(body)
    assert KEY not in json.dumps(headers)


def test_bodies_not_logged(upstream, log_path):
    rules = [{"method": "POST", "path": "/v1/projects"}]
    with proxy.serving(make_spec(upstream.url, rules), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, _ = call(p, "POST", "/v1/projects", body=b'{"name": "BODYMARKER-42"}',
                            headers={"Content-Type": "application/json"})
    assert status == 200
    assert upstream.requests[0]["body"] == b'{"name": "BODYMARKER-42"}'
    assert "BODYMARKER" not in log_path.read_text()


def test_body_limits(upstream, log_path):
    rules = [{"method": "POST", "path": "/v1/projects"}]
    with proxy.serving(make_spec(upstream.url, rules), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True, max_body=10) as p:
        assert call(p, "POST", "/v1/projects", body=b"x" * 11)[0] == 413
        assert call(p, "POST", "/v1/projects", body=b"x" * 10)[0] == 200
        chunked = raw(p, f"POST /v1/projects HTTP/1.1\r\nHost: x\r\n{proxy.TOKEN_HEADER}: {p.token}\r\n"
                         "Transfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n".encode())
        assert chunked.split(b" ")[1] == b"411"
    assert len(upstream.requests) == 1


def test_per_rule_upstream(upstream, upstream2, log_path):
    rules = [{"method": "GET", "path": "/v1/projects"},
             {"method": "POST", "path": "/uploads/**", "upstream": "https://uploads.example.com"}]
    parsed = proxy.parse_rules(rules)
    # parse_rules only takes https; the test swaps the second upstream for the local plain-http server
    parsed[1] = Rule("POST", "/uploads/**", upstream2.url)
    spec = ProxySpec("github", upstream.url, "Authorization", "Bearer {key}", tuple(parsed))
    with proxy.serving(spec, KEY, log_path=log_path, step="build", allow_plain_http_upstream=True) as p:
        assert call(p, "POST", "/uploads/a/b", body=b"data")[0] == 200
        assert call(p, "GET", "/v1/projects")[0] == 200
    assert [r["path"] for r in upstream2.requests] == ["/uploads/a/b"]
    assert [r["path"] for r in upstream.requests] == ["/v1/projects"]
    assert upstream2.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}"


def test_upstream_down_502_and_timeout_504(upstream, log_path):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_url = f"http://127.0.0.1:{dead.getsockname()[1]}"
    dead.close()
    with proxy.serving(make_spec(dead_url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, body = call(p, "GET", "/v1/projects")
    assert status == 502 and KEY.encode() not in body
    upstream.reply["sleep"] = 1.5
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True, upstream_timeout=0.3) as p:
        assert call(p, "GET", "/v1/projects")[0] == 504
    lines = log_lines(log_path)
    assert [(line["status"], line["reason"]) for line in lines] == [(502, "upstream unreachable"),
                                                                     (504, "upstream timeout")]


def test_redirect_not_followed(upstream, upstream2, log_path):
    upstream.reply.update(status=302, headers={"Location": upstream2.url + "/stolen"}, body=b"")
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, headers, _ = call(p, "GET", "/v1/projects")
    assert status == 302 and headers["Location"] == upstream2.url + "/stolen"
    assert len(upstream.requests) == 1 and upstream2.requests == []


def test_concurrent_requests(upstream, log_path):
    upstream.reply["sleep"] = 0.05
    results = []
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True, max_in_flight=20) as p:
        threads = [threading.Thread(target=lambda: results.append(call(p, "GET", "/v1/projects")[0]))
                   for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
    assert results == [200] * 20
    assert len(log_lines(log_path)) == 20
    assert len(upstream.requests) == 20
    assert all(r["headers"]["Authorization"] == f"Bearer {KEY}" for r in upstream.requests)


def test_stop_cleanly(upstream, log_path):
    with pytest.raises(RuntimeError):
        with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                           allow_plain_http_upstream=True) as p:
            assert call(p, "GET", "/v1/projects")[0] == 200
            raise RuntimeError("step failed")
    assert not p.thread.is_alive() and not p.running
    assert p._key is None
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", p.port), timeout=2).close()
    p.stop()
    p.stop()
    assert KEY not in repr(p) and p.token not in repr(p)


def test_plain_http_upstream_refused_unless_loopback_and_flag(log_path):
    with pytest.raises(ValueError, match="https"):
        proxy.serve(make_spec("http://127.0.0.1:9"), KEY, log_path=log_path, step="s")
    with pytest.raises(ValueError, match="https"):
        proxy.serve(make_spec("http://example.com"), KEY, log_path=log_path, step="s",
                    allow_plain_http_upstream=True)
    spec = ProxySpec("x", "https://api.example.com", "Authorization", "Bearer {key}",
                     (Rule("GET", "/a", "http://localhost:9"),))
    with pytest.raises(ValueError, match="https"):
        proxy.serve(spec, KEY, log_path=log_path, step="s")
    p = proxy.serve(make_spec("http://localhost:9"), KEY, log_path=log_path, step="s",
                    allow_plain_http_upstream=True)
    p.stop()


@pytest.mark.parametrize("item", [
    {"method": "FOO", "path": "/a"},
    {"method": "get", "path": "/a"},
    {"method": "GET", "path": "x/no-slash"},
    {"method": "GET", "path": "/a/**/b"},
    {"method": "GET", "path": "/a//b"},
    {"method": "GET", "path": "/a/../b"},
    {"method": "GET", "path": "/a/**/"},
    {"method": "GET", "path": "/a/b//"},
    {"method": "GET", "path": "/a/b*"},
    {"method": "GET", "path": "/a", "upstream": "http://uploads.example.com"},
    {"method": "GET", "path": "/a", "extra": 1},
])
def test_parse_rules_rejects_bad_rules(item):
    with pytest.raises(ValueError):
        proxy.parse_rules([item])


def test_trailing_slash_rule_matches_only_the_same_path():
    rules = proxy.parse_rules([{"method": "GET", "path": "/organizations/"}, {"method": "GET", "path": "/teams"}])
    assert proxy.find_rule(rules, "GET", "/organizations/") is rules[0]
    assert proxy.find_rule(rules, "GET", "/organizations") is None
    assert proxy.find_rule(rules, "GET", "/teams/") is None and proxy.find_rule(rules, "GET", "/teams") is rules[1]
    assert proxy.path_is_safe("/organizations/") and not proxy.path_is_safe("/organizations//")


def test_fake_proxy_factory_never_keeps_key(tmp_path):
    from fakes import FakeProxyFactory
    factory = FakeProxyFactory()
    spec = make_spec("https://api.supabase.com")
    handle = factory.start(spec, KEY, log_path=tmp_path / "p.jsonl", step="build", bind="127.0.0.1")
    assert handle.url == "http://proxy.fake/supabase" and handle.token == FakeProxyFactory.TOKEN
    assert factory.running() == ["supabase"]
    record = factory.started[0]
    assert record["key_len"] == len(KEY) and record["key_seen"] is True
    assert record["service"] == "supabase" and record["step"] == "build" and record["bind"] == "127.0.0.1"
    assert KEY not in repr(vars(factory)) and KEY not in repr(vars(handle))
    handle.stop()
    handle.stop()
    assert factory.stopped == ["supabase"] and factory.running() == []


def test_log_file_mode_0600(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects")
    assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o600


# ---------- extra safety checks beyond the 21 scenarios ----------

def test_gzip_reply_is_decoded_so_the_key_can_be_hidden(upstream, log_path):
    import gzip
    upstream.reply.update(body=gzip.compress(b"token=" + KEY.encode()), headers={"Content-Encoding": "gzip"})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, headers, body = call(p, "GET", "/v1/projects", headers={"Accept-Encoding": "gzip"})
    assert status == 200 and body == b"token=[redacted]" and "Content-Encoding" not in headers
    assert upstream.requests[0]["headers"]["Accept-Encoding"] == "identity"


def test_unknown_reply_encoding_refused(upstream, log_path):
    upstream.reply.update(body=b"\x00\x01opaque", headers={"Content-Encoding": "br"})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        assert call(p, "GET", "/v1/projects")[0] == 502


def test_caller_cannot_supply_spec_auth_header_or_extra_headers(upstream, log_path):
    spec = ProxySpec("sentry", upstream.url, "X-Api-Key", "{key}", tuple(proxy.parse_rules(
        [{"method": "GET", "path": "/v1/projects"}])), extra_headers=(("Accept", "application/json"),))
    with proxy.serving(spec, KEY, log_path=log_path, step="build", allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects", headers={"X-Api-Key": "evil", "Accept": "text/evil",
                                                "Connection": "close, X-Drop-Me", "X-Drop-Me": "1"})
    h = upstream.requests[0]["headers"]
    assert h["X-Api-Key"] == KEY and h["Accept"] == "application/json" and "X-Drop-Me" not in h


def test_bad_key_refused_without_echoing_it(log_path):
    with pytest.raises(ValueError) as e:
        proxy.serve(make_spec("https://api.example.com"), "sk-bad\r\nX-Evil: 1", log_path=log_path, step="s")
    assert "sk-bad" not in str(e.value)


def test_spec_from_service_reads_proxy_block():
    service = {"name": "github", "proxy": {
        "upstream": "https://api.github.com", "auth_header": "Authorization", "auth_format": "Bearer {key}",
        "key": "GH_TOKEN", "extra_headers": {"X-GitHub-Api-Version": "2022-11-28"},
        "allow": [{"method": "GET", "path": "/repos/*/*"},
                  {"method": "POST", "path": "/repos/*/*/releases/*/assets",
                   "upstream": "https://uploads.github.com"}]}}
    spec = proxy.spec_from_service(service)
    assert spec.service == "github" and spec.upstream == "https://api.github.com"
    assert spec.extra_headers == (("X-GitHub-Api-Version", "2022-11-28"),)
    assert spec.rules[1] == Rule("POST", "/repos/*/*/releases/*/assets", "https://uploads.github.com")


@pytest.mark.parametrize("change", [
    {"auth_format": "Bearer"}, {"auth_format": "{key}{key}"},
    {"upstream": "http://api.github.com"}, {"auth_header": "Host"}, {"auth_header": "Bad Header"},
    {"extra_headers": {"Authorization": "x"}}, {"extra_headers": {"X-A": "a\r\nb"}},
    {"extra_headers": {"Accept-Encoding": "gzip"}}, {"extra_headers": [["X-A", "a"]]},
    {"allow": [{"method": "GET", "path": "nope"}]}, {"allow": [{"method": "GET", "path": "/a;b"}]},
    {"allow": []}, {"surprise": 1}, {"key": 5},
])
def test_spec_from_service_rejects_broken_blocks(change):
    block = {**GOOD_BLOCK, **change}
    with pytest.raises(ValueError):
        proxy.spec_from_service({"name": "github", "proxy": block})


GOOD_BLOCK = {"upstream": "https://api.github.com", "auth_header": "Authorization", "auth_format": "Bearer {key}",
              "key": "GH_TOKEN", "allow": [{"method": "GET", "path": "/user"}]}


@pytest.mark.parametrize("missing", ["upstream", "auth_header", "auth_format", "key", "allow"])
def test_spec_from_service_requires_every_field_but_extra_headers(missing):
    block = {k: v for k, v in GOOD_BLOCK.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        proxy.spec_from_service({"name": "github", "proxy": block})
    assert proxy.spec_from_service({"name": "github", "proxy": GOOD_BLOCK}).extra_headers == ()


def test_auth_format_braces_other_than_key_are_kept_literally(upstream, log_path):
    spec = ProxySpec("svc", upstream.url, "Authorization", "Token {key} {other}", tuple(proxy.parse_rules(
        [{"method": "GET", "path": "/v1/projects"}])))
    with proxy.serving(spec, KEY, log_path=log_path, step="build", allow_plain_http_upstream=True) as p:
        call(p, "GET", "/v1/projects")
    assert upstream.requests[0]["headers"]["Authorization"] == f"Token {KEY} {{other}}"


def test_env_names():
    assert proxy.env_names("github-release") == ("PHOENIX_PROXY_GITHUB_RELEASE",
                                                 "PHOENIX_PROXY_TOKEN_GITHUB_RELEASE")


def test_real_adapter_starts_and_stops_a_proxy(upstream, log_path):
    from phoenix9.adapters import Proxy, real
    assert isinstance(real().proxy, Proxy)
    spec = make_spec(upstream.url)
    # the real adapter refuses plain-http upstreams (no test flag), so it is checked with an https spec
    p = Proxy().start(make_spec("https://api.supabase.com"), KEY, log_path=log_path, step="s")
    try:
        assert p.url == f"http://127.0.0.1:{p.port}" and len(p.token) >= 40
    finally:
        p.stop()
    with pytest.raises(ValueError):
        Proxy().start(spec, KEY, log_path=log_path, step="s")


# ---------- critic's fixes ----------

GH_RULES = [{"method": "GET", "path": "/repos/*/*"}, {"method": "DELETE", "path": "/repos/*/*/releases/*"}]


def raw_with_token(p, line: str, extra: str = "") -> bytes:
    """Send one raw request line with the right token header (plus any extra header lines)."""
    return raw(p, f"{line}\r\nHost: x\r\n{proxy.TOKEN_HEADER}: {p.token}\r\n{extra}\r\n".encode("latin-1"))


@pytest.mark.parametrize("line", ["GET //repos/o/r HTTP/1.1", "DELETE /repos/o/r#/releases/1 HTTP/1.1",
                                  "DELETE /repos/o/r;x/releases/1 HTTP/1.1", "GET /repos/o/r\u00e9 HTTP/1.1",
                                  "GET /repos/o/r?a=\x01 HTTP/1.1"])
def test_raw_request_line_tricks_refused_403(upstream, log_path, line):
    with proxy.serving(make_spec(upstream.url, GH_RULES), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        reply = raw_with_token(p, line)
    assert reply.split(b" ")[1] == b"403" and upstream.requests == []
    assert log_lines(log_path)[0]["reason"] == "unsafe path"


def test_two_token_headers_one_right_one_wrong_401(upstream, log_path):
    with proxy.serving(make_spec(upstream.url, GH_RULES), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        right_first = raw_with_token(p, "GET /repos/o/r HTTP/1.1", f"{proxy.TOKEN_HEADER}: wrong\r\n")
        assert right_first.split(b" ")[1] == b"401"
        wrong_first = raw(p, f"GET /repos/o/r HTTP/1.1\r\n{proxy.TOKEN_HEADER}: wrong\r\n"
                             f"{proxy.TOKEN_HEADER}: {p.token}\r\n\r\n".encode())
        assert wrong_first.split(b" ")[1] == b"401"
    assert upstream.requests == []


def test_gzip_reply_carrying_the_key_reaches_caller_redacted(upstream, log_path):
    import gzip
    upstream.reply.update(body=gzip.compress(json.dumps({"auth": f"Bearer {KEY}"}).encode()),
                          headers={"Content-Encoding": "gzip"})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, headers, body = call(p, "GET", "/v1/projects")
    assert status == 200 and KEY.encode() not in body and b"[redacted]" in body
    assert "Content-Encoding" not in headers


def test_br_reply_is_502(upstream, log_path):
    upstream.reply.update(body=b"\x1b\x00opaque" + KEY.encode(), headers={"Content-Encoding": "br"})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, body = call(p, "GET", "/v1/projects")
    assert status == 502 and KEY.encode() not in body


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "0", "localhost", "", "0x0", None])
def test_public_bind_refused(log_path, bind):
    with pytest.raises(ValueError):
        proxy.serve(make_spec("https://api.example.com"), KEY, log_path=log_path, step="s", bind=bind)


@pytest.mark.parametrize("key", ["sk-abc\ndef", "sk-abc\r\ndef"])
def test_key_with_line_break_refused_without_the_key_in_message(log_path, key):
    with pytest.raises(ValueError) as e:
        proxy.serve(make_spec("https://api.example.com"), key, log_path=log_path, step="s")
    assert "sk-abc" not in str(e.value) and "def" not in str(e.value)


def test_log_line_written_before_the_reply(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, _ = call(p, "GET", "/v1/nope")
        assert status == 403 and len(log_lines(log_path)) == 1   # already there when the reply arrived


def test_redact_percent_and_json_forms():
    key = "sk/a+b=c"
    data = ("q=" + "sk%2Fa%2Bb%3Dc" + ' j="sk\\/a+b=c"').encode()
    assert key.encode() not in proxy.redact(data, key)
    assert proxy.redact(data, key) == b'q=[redacted] j="[redacted]"'


# ---------- review fixes ----------

def _gz(data: bytes) -> bytes:
    import gzip
    return gzip.compress(data)


@pytest.mark.parametrize("encodings", [
    [("Content-Encoding", "gzip"), ("Content-Encoding", "gzip")],
    [("Content-Encoding", "gzip"), ("Content-Encoding", "identity")],
    [("Content-Encoding", "identity"), ("Content-Encoding", "gzip")],
    [("Content-Encoding", "gzip, gzip")],
    [("Content-Encoding", "gzip, br")],
    [("Content-Encoding", ",")],
])
def test_repeated_reply_encodings_are_502_never_a_leak(upstream, log_path, encodings):
    upstream.reply.update(body=_gz(_gz(b"token=" + KEY.encode())), headers=encodings)
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, body = call(p, "GET", "/v1/projects")
    assert status == 502 and KEY.encode() not in body


def test_reply_coding_rules():
    assert proxy.reply_coding([]) == "" and proxy.reply_coding([""]) == ""
    assert proxy.reply_coding(["identity"]) == "" and proxy.reply_coding([" GZIP "]) == "gzip"
    assert proxy.reply_coding(["gzip,"]) == "gzip" and proxy.reply_coding(["", "deflate"]) == "deflate"
    for bad in (["gzip", "gzip"], ["gzip", "identity"], ["identity, identity"], ["br"], [" , "]):
        assert proxy.reply_coding(bad) is None


def test_multi_member_gzip_reply_is_502(upstream, log_path):
    upstream.reply.update(body=_gz(b"first ") + _gz(b"token=" + KEY.encode()),
                          headers={"Content-Encoding": "gzip"})
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        status, _, body = call(p, "GET", "/v1/projects")
    assert status == 502 and KEY.encode() not in body


def test_folded_caller_header_refused_400_and_logged(upstream, log_path):
    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        reply = raw_with_token(p, "GET /v1/projects HTTP/1.1", "X-Note: one\r\n two\r\n")
    assert reply.split(b" ")[1] == b"400" and upstream.requests == []
    line = log_lines(log_path)[0]
    assert line["decision"] == "refused" and line["status"] == 400


def test_bind_must_be_a_specific_ip_literal(log_path):
    p = proxy.serve(make_spec("https://api.example.com"), KEY, log_path=log_path, step="s", bind="127.0.0.1")
    try:
        assert p.url.startswith("http://127.0.0.1:")
    finally:
        p.stop()


def test_concurrency_cap_refuses_extra_requests_503(upstream, log_path):
    upstream.reply["sleep"] = 1.5
    results = []
    lock = threading.Lock()

    def one():
        status = call(p, "GET", "/v1/projects")[0]
        with lock:
            results.append(status)

    with proxy.serving(make_spec(upstream.url), KEY, log_path=log_path, step="build",
                       allow_plain_http_upstream=True) as p:
        threads = [threading.Thread(target=one) for _ in range(proxy.MAX_IN_FLIGHT + 4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert sorted(results) == [200] * proxy.MAX_IN_FLIGHT + [503] * 4
        upstream.reply["sleep"] = 0
        assert call(p, "GET", "/v1/projects")[0] == 200   # slots come back
    busy = [ln for ln in log_lines(log_path) if ln["status"] == 503]
    assert len(busy) == 4 and all(ln["decision"] == "refused" and ln["reason"] == "too busy" for ln in busy)
    assert len(upstream.requests) == proxy.MAX_IN_FLIGHT + 1


# ---------- fixed port range (host firewall opens only these) ----------

def _free_block(n=3):
    """n consecutive ports that are free on 127.0.0.1 right now."""
    for base in range(41000, 46000, 7):
        socks = []
        try:
            for p in range(base, base + n):
                s = socket.socket()
                s.bind(("127.0.0.1", p))
                socks.append(s)
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    pytest.skip("no free block of ports")


def test_proxy_takes_first_free_port_in_range_and_skips_busy_ones(log_path):
    base = _free_block()
    busy = socket.socket()
    busy.bind(("127.0.0.1", base))
    busy.listen()
    spec = make_spec("https://api.example.com")
    try:
        a = proxy.serve(spec, KEY, log_path=log_path, step="s", ports=(base, base + 2))
        b = proxy.serve(spec, KEY, log_path=log_path, step="s", ports=(base, base + 2))
        try:
            assert (a.port, b.port) == (base + 1, base + 2)
            assert a.url == f"http://127.0.0.1:{base + 1}"
            with pytest.raises(proxy.NoFreePort, match=f"{base}-{base + 2}"):
                proxy.serve(spec, KEY, log_path=log_path, step="s", ports=(base, base + 2))
        finally:
            a.stop()
            b.stop()
        c = proxy.serve(spec, KEY, log_path=log_path, step="s", ports=(base, base + 2))
        assert c.port == base + 1          # a stopped proxy's port is free again
        c.stop()
    finally:
        busy.close()


def test_real_adapter_uses_the_configured_range(log_path, phoenix_env):
    from phoenix9.adapters import Proxy
    base = _free_block(2)
    (phoenix_env["home"] / "config").mkdir(parents=True, exist_ok=True)
    (phoenix_env["home"] / "config" / "global.toml").write_text(f'proxy_ports = "{base}-{base + 1}"\n')
    p = Proxy().start(make_spec("https://api.supabase.com"), KEY, log_path=log_path, step="s")
    try:
        assert p.port == base
    finally:
        p.stop()


def test_bad_range_refused(log_path):
    with pytest.raises(ValueError):
        proxy.serve(make_spec("https://api.example.com"), KEY, log_path=log_path, step="s", ports=(5000, 4000))


def test_shipped_sentry_and_cloudflare_rules_match_new_calls():
    from phoenix9 import services
    sentry = proxy.parse_rules(services.get("sentry")["proxy"]["allow"])
    assert proxy.find_rule(sentry, "POST", "/teams/org/team/projects/")
    assert proxy.find_rule(sentry, "GET", "/projects/org/slug/keys/")
    assert proxy.find_rule(sentry, "POST", "/teams/org/team/projects") is None
    assert proxy.find_rule(sentry, "GET", "/projects/org/slug/keys") is None
    cloudflare = proxy.parse_rules(services.get("cloudflare")["proxy"]["allow"])
    assert proxy.find_rule(cloudflare, "GET", "/accounts/abc123/tokens/verify")
    assert proxy.find_rule(cloudflare, "POST", "/accounts/abc123/tokens/verify") is None
