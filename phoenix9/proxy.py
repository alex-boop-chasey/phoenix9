"""Key proxy: a small per-step HTTP forwarder that holds one service's account key and adds it on the way out.

The caller (a step container or a host script) only gets an address and a random per-step token. The
proxy forwards only the calls declared for the service (method + path pattern), refuses everything
else, writes one JSON line per request (never bodies, headers or query values) and stops with the step.

Layout: the rules and the yes/no decision are pure functions (`parse_rules`, `path_is_safe`,
`pattern_matches`, `decide`, `outgoing_headers`, `redact`); the I/O lives in `forward`, `LogWriter`,
the request handler and `RunningProxy`.
"""
import base64
import gzip
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import ssl
import string
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote, urlsplit

from phoenix9 import scrub

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
TOKEN_HEADER = "X-Phoenix-Proxy-Token"
REDACTED = b"[redacted]"
MAX_RESPONSE = 50_000_000
LOG_PATH_MAX = 2000
UNSAFE_ENCODINGS = ("%2e", "%2f", "%5c", "%00")
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection",
              "te", "trailer", "transfer-encoding", "upgrade"}
# Never copied from the caller: hop-by-hop, plus everything the proxy sets itself or must never pass on.
CALLER_DROPPED = HOP_BY_HOP | {"host", "authorization", "cookie", TOKEN_HEADER.lower(), "content-length",
                               "expect", "accept-encoding"}
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
# The only raw characters a request path may carry (no ;, #, ?, space, quotes, non-ASCII, ...).
SAFE_PATH_CHARS = frozenset(string.ascii_letters + string.digits + "-._~%:@!$&'()*+,=/")
PROXY_FIELDS = {"upstream", "auth_header", "auth_format", "key", "extra_headers", "allow"}
# The reply codings the proxy can undo to look for the key; anything else (or more than one) is a 502.
REPLY_CODINGS = ("identity", "gzip", "x-gzip", "deflate")
MAX_IN_FLIGHT = 8   # forwarded requests at once per proxy; more get 503 straight away


@dataclass(frozen=True)
class Rule:
    """One declared call: a method and a path pattern, optionally sent to its own upstream."""

    method: str
    path: str
    upstream: str = ""


@dataclass(frozen=True)
class ProxySpec:
    """Everything the proxy needs to know about one service, except the key."""

    service: str
    upstream: str
    auth_header: str
    auth_format: str
    rules: tuple[Rule, ...]
    extra_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Decision:
    """The proxy's answer to one request: allowed or not, and why (no I/O behind it)."""

    allowed: bool
    status: int = 200
    reason: str = ""
    rule: Rule | None = None
    path: str = ""          # raw path without the query
    query: str = ""         # "" or "?..." exactly as sent
    body_length: int = 0


# ---------- rules (pure) ----------

def _check_upstream(url: str, *, allow_plain_http: bool = False) -> None:
    """Raise ValueError unless the upstream is https://host[:port][/base] (or loopback http when allowed)."""
    if not isinstance(url, str) or not url:
        raise ValueError("the upstream address is empty")
    parts = urlsplit(url)
    if parts.scheme == "http":
        if not (allow_plain_http and parts.hostname in LOOPBACK_HOSTS):
            raise ValueError(f"upstream {url} must use https (plain http is only for local tests)")
    elif parts.scheme != "https":
        raise ValueError(f"upstream {url} must start with https://")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"upstream {url} must be just https://host with an optional base path")
    if "\\" in url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError(f"upstream {url!r} has characters that are not allowed")


def _check_pattern(path) -> None:
    """Raise ValueError unless the pattern is a clean /a/*/b or /a/** style path."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"rule path {path!r} must start with /")
    segments = path.split("/")[1:]
    for i, seg in enumerate(segments):
        if seg == "":
            raise ValueError(f"rule path {path} has an empty part (// or a trailing /)")
        if seg in (".", ".."):
            raise ValueError(f"rule path {path} must not contain . or .. parts")
        if seg == "**" and i != len(segments) - 1:
            raise ValueError(f"rule path {path}: ** is only allowed as the last part")
        if seg not in ("*", "**") and ("*" in seg or any(c in seg for c in "%\\?#;")):
            raise ValueError(f"rule path {path}: part {seg!r} may not contain * % \\ ? # or ;")
        if any(ord(c) < 32 or ord(c) == 127 for c in seg):
            raise ValueError(f"rule path {path!r} has control characters")


def parse_rules(items: list[dict]) -> list[Rule]:
    """Turn [{method, path, upstream?}, ...] into Rules; a bad rule raises ValueError in plain English."""
    if not isinstance(items, list):
        raise ValueError("the allowed calls must be a list of {method, path} tables")
    rules = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"allowed call {n} must be a table with method and path")
        extra = set(item) - {"method", "path", "upstream"}
        if extra:
            raise ValueError(f"allowed call {n} has unknown fields: {', '.join(sorted(extra))}")
        method = item.get("method")
        if method not in METHODS:
            raise ValueError(f"allowed call {n}: method {method!r} must be one of {' '.join(METHODS)}")
        _check_pattern(item.get("path"))
        upstream = item.get("upstream", "")
        if upstream:
            _check_upstream(upstream)
        rules.append(Rule(method=method, path=item["path"], upstream=upstream))
    return rules


def _check_header(name: str, value: str, what: str) -> None:
    """Raise ValueError unless the header name and value are safe to send."""
    if not name or any(c in name for c in " :\t\r\n") or any(ord(c) < 33 or ord(c) > 126 for c in name):
        raise ValueError(f"{what} header name {name!r} is not valid")
    if name.lower() in HOP_BY_HOP | {"host", "content-length", "cookie", "accept-encoding", TOKEN_HEADER.lower()}:
        raise ValueError(f"{what} header {name} is not allowed")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{what} header {name} has control characters in its value")


def spec_from_service(service: dict) -> ProxySpec:
    """Build a ProxySpec from a service.toml dict and its [proxy] block (ValueError when it is broken).

    [proxy] fields: upstream, auth_header, auth_format, key, allow (all required) and extra_headers
    (optional table). `key` names the key and is not used here, only checked to be text.
    """
    name = service.get("name") if isinstance(service, dict) else None
    block = service.get("proxy") if isinstance(service, dict) else None
    if not name or not isinstance(block, dict):
        raise ValueError(f"service {name or '?'} has no [proxy] block")
    unknown = set(block) - PROXY_FIELDS
    if unknown:
        raise ValueError(f"service {name}: [proxy] has unknown fields: {', '.join(sorted(unknown))}")
    missing = PROXY_FIELDS - {"extra_headers"} - set(block)
    if missing:
        raise ValueError(f"service {name}: [proxy] is missing {', '.join(sorted(missing))}")
    if not isinstance(block["key"], str):
        raise ValueError(f"service {name}: [proxy] key must be text")
    upstream = block["upstream"]
    _check_upstream(upstream)
    auth_header = block["auth_header"]
    auth_format = block["auth_format"]
    if not isinstance(auth_header, str):
        raise ValueError(f"service {name}: auth_header must be text")
    if not isinstance(auth_format, str) or auth_format.count("{key}") != 1:
        raise ValueError(f"service {name}: auth_format must contain {{key}} exactly once")
    _check_header(auth_header, auth_format, f"service {name} auth")
    extra = block.get("extra_headers", {})
    if not isinstance(extra, dict):
        raise ValueError(f"service {name}: extra_headers must be a table of name = value")
    pairs = list(extra.items())
    for k, v in pairs:
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(f"service {name}: extra_headers must be text")
        _check_header(k, v, f"service {name} extra")
        if k.lower() == auth_header.lower():
            raise ValueError(f"service {name}: extra_headers must not set the auth header")
    allow = block["allow"]
    if not isinstance(allow, list) or not allow:
        raise ValueError(f"service {name}: [proxy] allow must list at least one call")
    rules = parse_rules(allow)
    return ProxySpec(service=name, upstream=upstream, auth_header=auth_header, auth_format=auth_format,
                     rules=tuple(rules), extra_headers=tuple(pairs))


# ---------- decisions (pure) ----------

def path_is_safe(raw_path: str) -> bool:
    """True when the path (no query) has no dot parts, //, backslash, control characters or sneaky encodings."""
    if not raw_path.startswith("/") or any(c not in SAFE_PATH_CHARS for c in raw_path):
        return False
    try:
        decoded = unquote(raw_path, errors="strict")
    except UnicodeDecodeError:
        return False
    for form in (raw_path, decoded):
        if any(e in form.lower() for e in UNSAFE_ENCODINGS):
            return False
        if "\\" in form or "//" in form or any(ord(c) < 32 or ord(c) == 127 for c in form):
            return False
        if any(seg in (".", "..") for seg in form.split("/")[1:]):
            return False
    return True


def pattern_matches(pattern: str, path: str) -> bool:
    """True when the path fits the pattern: * = exactly one non-empty part, ** (last) = one or more parts."""
    want = pattern.split("/")[1:]
    got = path.split("/")[1:]
    if want and want[-1] == "**":
        head = want[:-1]
        if len(got) <= len(head) or not all(got[len(head):]):
            return False
        return all(_segment_matches(w, g) for w, g in zip(head, got))
    return len(want) == len(got) and all(_segment_matches(w, g) for w, g in zip(want, got))


def _segment_matches(want: str, got: str) -> bool:
    """One part: * matches any non-empty part; anything else must be equal (case-sensitive)."""
    return bool(got) if want == "*" else want == got


def find_rule(rules, method: str, path: str) -> Rule | None:
    """The first rule with this method whose pattern matches the path, else None."""
    for rule in rules:
        if rule.method == method and pattern_matches(rule.path, path):
            return rule
    return None


def _token_ok(token: str, sent: list[str]) -> bool:
    """True when exactly one token header was sent and it equals the proxy token."""
    if len(sent) != 1:
        return False
    return hmac.compare_digest(sent[0].encode("utf-8", "replace"), token.encode("utf-8"))


def decide(spec: ProxySpec, token: str, method: str, target: str, headers, *, max_body: int) -> Decision:
    """Decide what to do with one request (no I/O): the token, request line, path, rules and body size."""
    path, _, query = target.partition("?")
    query = "?" + query if "?" in target else ""
    if not _token_ok(token, headers.get_all(TOKEN_HEADER) or []):
        return Decision(False, 401, "bad token", path=path, query=query)
    if any("\r" in n or "\n" in n or "\r" in v or "\n" in v for n, v in headers.items()):
        return Decision(False, 400, "folded or broken header", path=path, query=query)
    if method not in METHODS:
        return Decision(False, 405, f"method {method[:20]} not allowed", path=path, query=query)
    if not target.startswith("/"):
        return Decision(False, 403, "not an origin-form path", path=path, query=query)
    if not path_is_safe(path) or any(ord(c) < 32 or ord(c) == 127 for c in query):
        return Decision(False, 403, "unsafe path", path=path, query=query)
    rule = find_rule(spec.rules, method, path)
    if rule is None:
        return Decision(False, 403, "not a declared call", path=path, query=query)
    if headers.get_all("Transfer-Encoding"):
        return Decision(False, 411, "chunked body", path=path, query=query)
    lengths = headers.get_all("Content-Length") or []
    if len(lengths) > 1 or (lengths and not lengths[0].strip().isdigit()):
        return Decision(False, 400, "bad Content-Length", path=path, query=query)
    length = int(lengths[0]) if lengths else 0
    if length > max_body:
        return Decision(False, 413, "body too large", path=path, query=query)
    return Decision(True, 200, "", rule=rule, path=path, query=query, body_length=length)


def outgoing_headers(spec: ProxySpec, key: str, caller: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The headers sent upstream: the caller's minus the dropped ones, then the key and the extra headers."""
    named_in_connection = set()
    for name, value in caller:
        if name.lower() == "connection":
            named_in_connection |= {v.strip().lower() for v in value.split(",")}
    dropped = CALLER_DROPPED | named_in_connection | {spec.auth_header.lower()}
    dropped |= {k.lower() for k, _ in spec.extra_headers}
    out = [(n, v) for n, v in caller if n.lower() not in dropped]
    out.append((spec.auth_header, spec.auth_format.replace("{key}", key)))
    out.extend(spec.extra_headers)
    out.append(("Accept-Encoding", "identity"))
    return out


def key_forms(key: str) -> list[bytes]:
    """The byte forms of the key to hide in replies: as is, base64 (padded and not), url-safe base64,
    percent-encoded and JSON-escaped (also with / written as \\/)."""
    raw = key.encode("utf-8")
    as_json = json.dumps(key)[1:-1]
    forms = {raw, base64.b64encode(raw), base64.b64encode(raw).rstrip(b"="),
             base64.urlsafe_b64encode(raw).rstrip(b"="), quote(key, safe="").encode("utf-8"),
             as_json.encode("utf-8"), as_json.replace("/", "\\/").encode("utf-8")}
    return sorted((f for f in forms if f), key=len, reverse=True)


def redact(data: bytes, key: str) -> bytes:
    """Replace every form of the key in the bytes with [redacted]."""
    for form in key_forms(key):
        data = data.replace(form, REDACTED)
    return data


# ---------- I/O: log, forward, handler, lifecycle ----------

class LogWriter:
    """Appends one scrubbed JSON line per request to the proxy log (file 0600, folders made)."""

    def __init__(self, path: Path, service: str, step: str, key: str):
        """Remember where and what to write; the key is only kept to scrub it out."""
        self.path = Path(path)
        self.service = service
        self.step = step
        self._scrubber = scrub.Scrubber([key])
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
        os.chmod(self.path, 0o600)

    def write(self, method: str, path: str, query: bool, decision: str, reason: str, status: int,
              ms: int) -> None:
        """Write one line: when, which step, method, path (no query values), the decision and status."""
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "service": self.service,
                           "step": self.step, "method": method[:20], "path": path[:LOG_PATH_MAX],
                           "query": query, "decision": decision, "reason": reason, "status": status,
                           "ms": ms})
        line = scrub.scrub(self._scrubber.text(line))
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)

    def forget_key(self) -> None:
        """Drop the key (after the proxy stops)."""
        self._scrubber = scrub.Scrubber()


@dataclass
class Reply:
    """What goes back to the caller."""

    status: int
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    reason: str = ""


def _plain(status: int, text: str) -> Reply:
    """A short plain-text reply made by the proxy itself."""
    return Reply(status, [("Content-Type", "text/plain; charset=utf-8")], (text + "\n").encode(), text)


def _decode_body(body: bytes, encoding: str) -> bytes | None:
    """Undo gzip/deflate so the key can be found (None when the encoding is unknown or too big)."""
    try:
        if encoding in ("gzip", "x-gzip"):
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            d = zlib.decompressobj()
        else:
            return None
        out = d.decompress(body, MAX_RESPONSE + 1)
        # unused_data: a second gzip member (or junk) after the first, which would go out undecoded
        return None if len(out) > MAX_RESPONSE or d.unconsumed_tail or d.unused_data else out
    except (zlib.error, gzip.BadGzipFile):
        return None


def forward(spec: ProxySpec, key: str, decision: Decision, method: str, caller_headers, body: bytes | None,
            *, timeout: float, allow_plain_http: bool) -> Reply:
    """Send one allowed request upstream with the key added; return the reply with the key hidden."""
    upstream = urlsplit(decision.rule.upstream or spec.upstream)
    base = upstream.path.rstrip("/")
    if upstream.scheme == "https":
        conn = http.client.HTTPSConnection(upstream.hostname, upstream.port, timeout=timeout,
                                           context=ssl.create_default_context())
    elif allow_plain_http and upstream.hostname in LOOPBACK_HOSTS:
        conn = http.client.HTTPConnection(upstream.hostname, upstream.port, timeout=timeout)
    else:
        return _plain(502, "upstream not allowed")
    try:
        conn.putrequest(method, base + decision.path + decision.query, skip_accept_encoding=True)
        for name, value in outgoing_headers(spec, key, caller_headers):
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        resp = conn.getresponse()
        data = resp.read(MAX_RESPONSE + 1)
        status, raw_headers = resp.status, resp.getheaders()
    except TimeoutError:
        return _plain(504, "upstream timeout")
    except (OSError, http.client.HTTPException, ValueError):
        return _plain(502, "upstream unreachable")
    finally:
        conn.close()
    if len(data) > MAX_RESPONSE:
        return _plain(502, "upstream reply too large")
    return _reply_from_upstream(status, raw_headers, data, key, method)


def reply_coding(values: list[str]) -> str | None:
    """The one content coding named by all Content-Encoding headers together ("" = none), or None when
    they name an unknown coding, more than one coding, or nothing at all in a non-empty header."""
    codings = [c.strip().lower() for v in values for c in v.split(",") if c.strip()]
    if not codings:
        return None if any(v.strip() for v in values) else ""
    if len(codings) != 1 or codings[0] not in REPLY_CODINGS:
        return None
    return "" if codings[0] == "identity" else codings[0]


def _reply_from_upstream(status: int, raw_headers, data: bytes, key: str, method: str) -> Reply:
    """Copy the upstream reply minus hop-by-hop headers, with every form of the key hidden."""
    encodings = []
    headers = []
    upstream_length = ""
    for name, value in raw_headers:
        low = name.lower()
        if low in HOP_BY_HOP:
            continue
        if low == "content-length":
            upstream_length = value
            continue
        if low == "content-encoding":
            encodings.append(value)   # every one: keeping only the last let gzip + gzip through undecoded
            continue
        headers.append((name, value))
    encoding = reply_coding(encodings)
    if encoding is None:
        return _plain(502, "upstream reply encoding not supported")
    if encoding and data:
        data = _decode_body(data, encoding)
        if data is None:
            return _plain(502, "upstream reply encoding not supported")
    elif encoding:
        headers.append(("Content-Encoding", encoding))
    data = redact(data, key)
    headers = [(redact(n.encode("latin-1", "replace"), key).decode("latin-1"),
                redact(v.encode("latin-1", "replace"), key).decode("latin-1")) for n, v in headers]
    if method == "HEAD":
        if upstream_length.strip().isdigit():
            headers.append(("Content-Length", upstream_length.strip()))
    elif not (100 <= status < 200 or status in (204, 304)):
        headers.append(("Content-Length", str(len(data))))
    return Reply(status, headers, b"" if method == "HEAD" else data, "")


class _Server(ThreadingHTTPServer):
    """The listening server: daemon threads, quiet errors, a link back to its RunningProxy."""

    daemon_threads = True
    allow_reuse_address = True
    owner: "RunningProxy"

    def handle_error(self, request, client_address):
        """Stay quiet: no tracebacks on stderr (they could carry request details)."""


class _Handler(BaseHTTPRequestHandler):
    """Reads one request, asks decide(), forwards or refuses, replies, logs."""

    protocol_version = "HTTP/1.0"
    server_version = "phoenix-proxy"
    sys_version = ""
    timeout = 120   # a caller that goes quiet cannot hold a thread forever

    def __getattr__(self, name: str):
        """Every do_<METHOD> (GET, CONNECT, anything) goes to the one handler, so all are decided and logged."""
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def log_message(self, format, *args):
        """No stderr logging; the JSON log is the record."""

    def send_error(self, code, message=None, explain=None):
        """A malformed request line or header block: plain refusal, logged."""
        owner = self.server.owner
        owner.log.write(getattr(self, "command", None) or "-", "-", False, "refused", "bad request", code, 0)
        self._send(_plain(code, "bad request"))

    def _send(self, reply: Reply) -> None:
        """Write the reply to the caller."""
        try:
            self.send_response_only(reply.status)
            for name, value in reply.headers:
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            if reply.body:
                self.wfile.write(reply.body)
        except OSError:
            pass

    def _handle(self) -> None:
        """Handle one request of any method."""
        owner = self.server.owner
        start = time.monotonic()
        words = self.requestline.split()
        target = words[1] if len(words) >= 2 else ""   # raw target: self.path collapses a leading //
        d = Decision(False, 502, "proxy error", path=target.partition("?")[0], query="")
        try:
            d = decide(owner.spec, owner.token, self.command, target, self.headers, max_body=owner.max_body)
            if d.allowed and not owner._slots.acquire(blocking=False):
                d = Decision(False, 503, "too busy", path=d.path, query=d.query)
            if not d.allowed:
                reply = _plain(d.status, f"refused: {d.reason}")
            else:
                try:
                    reply = self._forward(owner, d)
                finally:
                    owner._slots.release()
        except Exception:   # never let an error (and its message) reach the caller or stderr
            reply = _plain(502, "proxy error")
        decision = "forwarded" if d.allowed else "refused"
        reason = reply.reason if d.allowed else d.reason
        # Log before answering; a failed log write is not caught (the connection just closes, no reply).
        owner.log.write(self.command, d.path, "?" in target, decision, reason, reply.status,
                        int((time.monotonic() - start) * 1000))
        self._send(reply)

    def _forward(self, owner: "RunningProxy", d: Decision) -> Reply:
        """Read the body and forward the allowed request."""
        body = self.rfile.read(d.body_length) if d.body_length else None
        if body is not None and len(body) != d.body_length:
            return _plain(400, "body shorter than Content-Length")
        if body is None and (self.command in ("POST", "PUT", "PATCH") or "Content-Length" in self.headers):
            body = b""
        key = owner._key
        if key is None:
            return _plain(503, "proxy stopped")
        return forward(owner.spec, key, d, self.command, list(self.headers.items()), body,
                       timeout=owner.upstream_timeout, allow_plain_http=owner.allow_plain_http)


class RunningProxy:
    """A started proxy: .url, .token, .port for the caller, .stop() when the step ends (safe to call twice)."""

    def __init__(self, spec: ProxySpec, key: str, log: LogWriter, server: _Server, *, bind: str,
                 upstream_timeout: float, max_body: int, allow_plain_http: bool,
                 max_in_flight: int = MAX_IN_FLIGHT):
        """Hold the running server; use serve() to make one."""
        self.spec = spec
        self.token = secrets.token_urlsafe(32)
        self._key: str | None = key
        self.log = log
        self.upstream_timeout = upstream_timeout
        self.max_body = max_body
        self.allow_plain_http = allow_plain_http
        self._slots = threading.BoundedSemaphore(max_in_flight)   # caps forwarded requests (and their memory)
        self._server = server
        self.port = server.server_address[1]
        self.url = f"http://{bind}:{self.port}"
        self._stopped = False
        self._lock = threading.Lock()
        server.owner = self
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name=f"phoenix-proxy-{spec.service}", daemon=True)
        self._thread.start()

    def __repr__(self) -> str:
        """Show the service and address only (never the key or token)."""
        return f"<RunningProxy {self.spec.service} {self.url}{' stopped' if self._stopped else ''}>"

    @property
    def running(self) -> bool:
        """True until stop() has finished."""
        return not self._stopped

    @property
    def thread(self) -> threading.Thread:
        """The server thread (for tests: gone after stop)."""
        return self._thread

    def stop(self) -> None:
        """Stop serving, close the socket, wait for the thread (5 s) and drop the key; safe to repeat."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            try:
                self._server.shutdown()
            finally:
                self._server.server_close()
                self._thread.join(5)
                self._key = None
                self.log.forget_key()


def _check_key(key) -> None:
    """Raise ValueError (without the key in it) unless the key is usable in a header."""
    if not isinstance(key, str) or not key:
        raise ValueError("the account key is empty")
    if any(ord(c) <= 32 or ord(c) >= 127 for c in key):
        raise ValueError("the account key has spaces or characters that cannot go in a header")


def _check_bind(bind) -> None:
    """Raise ValueError unless bind is one IP address literal that is not 'every address' (0.0.0.0, ::)."""
    if not isinstance(bind, str):
        raise ValueError("the proxy's listen address must be text like 127.0.0.1")
    try:
        addr = ipaddress.ip_address(bind)
    except ValueError:
        raise ValueError(f"the proxy must listen on an IP address like 127.0.0.1, not {bind!r}") from None
    if addr.is_unspecified:
        raise ValueError(f"the proxy must not listen on every address ({bind}); use 127.0.0.1")


def serve(spec: ProxySpec, key: str, *, log_path: Path, step: str, bind: str = "127.0.0.1", port: int = 0,
          upstream_timeout: float = 30.0, max_body: int = 10_000_000,
          allow_plain_http_upstream: bool = False, max_in_flight: int = MAX_IN_FLIGHT) -> RunningProxy:
    """Start a proxy for one service and one step; returns the running handle (address, token, stop)."""
    _check_key(key)
    _check_bind(bind)
    if not isinstance(max_in_flight, int) or max_in_flight < 1:
        raise ValueError("max_in_flight must be a whole number of at least 1")
    _check_upstream(spec.upstream, allow_plain_http=allow_plain_http_upstream)
    for rule in spec.rules:
        if rule.upstream:
            _check_upstream(rule.upstream, allow_plain_http=allow_plain_http_upstream)
    if spec.auth_format.count("{key}") != 1:
        raise ValueError("auth_format must contain {key} exactly once")
    log = LogWriter(log_path, spec.service, step, key)
    server = _Server((bind, port), _Handler)
    return RunningProxy(spec, key, log, server, bind=bind, upstream_timeout=upstream_timeout,
                        max_body=max_body, allow_plain_http=allow_plain_http_upstream,
                        max_in_flight=max_in_flight)


@contextmanager
def serving(spec: ProxySpec, key: str, **kw) -> Iterator[RunningProxy]:
    """Run a proxy for the length of a with-block; it is stopped even when the block raises."""
    proxy = serve(spec, key, **kw)
    try:
        yield proxy
    finally:
        proxy.stop()


def env_names(service: str) -> tuple[str, str]:
    """The container env var names for a service's proxy address and token."""
    up = service.upper().replace("-", "_")
    return f"PHOENIX_PROXY_{up}", f"PHOENIX_PROXY_TOKEN_{up}"
