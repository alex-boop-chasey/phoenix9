"""Tests for the write guard: the peer must be a root process, the agent send context is cleaned, and the optional
Cloudflare Access lock (a signed token on every write when global.toml [access] is set)."""
import json
import socket
import time
import types

import pytest

from helpers import rsatest
from phoenix9 import access, adapters, agentlink, paths
from phoenix9.ops import common
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

TEAM = "rebirth.cloudflareaccess.com"
AUD = "aud-tag-1234567890"
CERTS = f"https://{TEAM}/cdn-cgi/access/certs"


@pytest.fixture
def fakes(api, monkeypatch):
    """The fake adapters the api fixture's server is using."""
    return common.make_adapters()


# ---- the peer must be a root process ----

def test_write_from_a_non_root_process_is_refused(api, fakes, monkeypatch):
    """A POST from a program run by another user (e.g. grunt, uid 1000) gets 403 with a plain message."""
    sent = []
    monkeypatch.setattr(agentlink, "send", lambda *a, **k: sent.append(a) or {"sent": True})
    fakes.host.peer_uid = 1000
    status, body = api("/api/agent/send", "POST", POST_HEADERS, {"text": "hi"})
    assert status == 403 and body["ok"] is False
    assert "root" in body["message"] and "uid" not in body["message"].lower()
    assert sent == []
    assert api("/api/projects", "POST", POST_HEADERS, {})[0] == 403


def test_reads_do_not_need_a_root_peer(api, fakes):
    fakes.host.peer_uid = 1000
    assert api("/api/health")[0] == 200


def test_unknown_peer_is_refused(api, fakes):
    """When the owner of the connection cannot be found, the write is refused (never let through)."""
    fakes.host.peer_uid = None
    status, body = api("/api/anything", "POST", POST_HEADERS, {})
    assert status == 403 and "couldn't tell" in body["message"]


def test_root_peer_passes_the_guard(api, fakes):
    fakes.host.peer_uid = 0
    assert api("/api/anything", "POST", POST_HEADERS, {})[0] == 404
    assert fakes.host.socket_lookups and fakes.host.socket_lookups[-1][1][1] == int(api.base.rsplit(":", 1)[1])


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_other_write_methods_go_through_the_guard(api, fakes, method):
    fakes.host.peer_uid = 1000
    assert api("/api/anything", method, POST_HEADERS, {})[0] == 403
    fakes.host.peer_uid = 0
    assert api("/api/anything", method, POST_HEADERS, {})[0] == 404


def _proc_line(n, local, remote, uid):
    return (f"  {n}: {local} {remote} 01 00000000:00000000 00:00000000 00000000  {uid:>4}        0 1234 1 "
            "0000000000000000 20 4 30 10 -1\n")


def test_host_socket_uid_reads_proc_net_tcp(tmp_path):
    """The real host finds the uid of the socket whose local and remote ends match, in tcp and tcp6."""
    head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    tcp = tmp_path / "tcp"
    tcp6 = tmp_path / "tcp6"
    # 127.0.0.1:50000 -> 127.0.0.1:8095 owned by 1000; the server's own end (8095 -> 50000) owned by 0
    tcp.write_text(head + _proc_line(0, "0100007F:C350", "0100007F:1F9F", 1000)
                   + _proc_line(1, "0100007F:1F9F", "0100007F:C350", 0))
    v6 = "0000000000000000FFFF00000100007F"
    tcp6.write_text(head + _proc_line(0, f"{v6}:C351", f"{v6}:1F9F", 0))
    host = adapters.Host()
    tables = (str(tcp), str(tcp6))
    assert host.socket_uid(("127.0.0.1", 50000), ("127.0.0.1", 8095), tables) == 1000
    assert host.socket_uid(("::ffff:127.0.0.1", 50001), ("::ffff:127.0.0.1", 8095), tables) == 0
    assert host.socket_uid(("127.0.0.1", 50002), ("127.0.0.1", 8095), tables) is None
    tcp.write_text(head + _proc_line(0, "0100007F:C350", "0100007F:1F9F", 1000)
                   + _proc_line(1, "0100007F:C350", "0100007F:1F9F", 0))
    assert host.socket_uid(("127.0.0.1", 50000), ("127.0.0.1", 8095), tables) is None   # two owners: unsure


def test_host_socket_uid_on_a_real_connection():
    """On Linux, a real loopback connection made by this process shows this process's uid."""
    import os
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    cli = socket.create_connection(srv.getsockname())
    try:
        assert adapters.Host().socket_uid(cli.getsockname(), srv.getsockname()) == os.getuid()
    finally:
        cli.close()
        srv.close()


# ---- the agent send context ----

@pytest.fixture
def captured(monkeypatch, tmp_path):
    """agentlink.send with a pretend live session; returns the lines written to the inbox."""
    wrote = []
    found = {"pid": 1, "session_id": "s", "name": "Phoenix agent", "socket": "x", "transcript": None,
             "status": "idle"}
    monkeypatch.setattr(agentlink, "find", lambda *a, **k: found)
    monkeypatch.setattr(agentlink, "connect_and_write", lambda path, data, timeout=0: wrote.append(data))
    return wrote


def first_line(raw):
    content = json.loads(raw)["message"]["content"]
    return content.split("\n")[1]


def test_context_unknown_project_is_dropped(captured):
    make_project("alpha")
    agentlink.send("hi", {"project": "alpha"})
    assert "project: alpha · folder: /srv/projects/alpha" in first_line(captured[-1])
    agentlink.send("hi", {"project": "../../etc", "page": "home"})
    line = first_line(captured[-1])
    assert "etc" not in line and "project:" not in line and "page: home · folder: /srv/projects/home]" in line


@pytest.mark.parametrize("bad", ["a b", "x" * 81, "<script>", "home x", "a;rm -rf", ""])
def test_context_page_and_run_must_match_the_pattern(captured, bad):
    agentlink.send("hi", {"page": bad, "run": bad})
    assert len(captured[-1].splitlines()) == 1
    assert "page:" not in first_line(captured[-1]) and "run:" not in first_line(captured[-1])


def test_context_newlines_are_stripped(captured):
    make_project("alpha")
    agentlink.send("hi", {"page": "home\n", "run": "2026\r\n-r1", "project": "al\npha"})
    line = first_line(captured[-1])
    assert "page: home" in line and "run: 2026-r1" in line and "project: alpha" in line
    body = json.loads(captured[-1])["message"]["content"]
    assert body.split("\n")[2] == "hi"


def test_context_folder_is_a_listed_project_or_the_agent_folder(captured):
    agentlink.send("hi", {"project": "ghost", "run": "r1"})
    assert "folder: /srv/projects/home" in first_line(captured[-1])


def test_context_values_that_are_not_text_are_dropped(captured):
    agentlink.send("hi", {"page": 7, "run": ["x"], "project": None, "extra": "no"})
    assert json.loads(captured[-1])["message"]["content"].split("\n")[1] == "hi"


# ---- the optional Cloudflare Access lock ----

@pytest.fixture(scope="module")
def key():
    return rsatest.make_key(1024)


@pytest.fixture
def locked(fakes, key, monkeypatch):
    """global.toml [access] set and the team's certs served by the fake http adapter."""
    access.clear_cache()
    (paths.home() / "config").mkdir(parents=True, exist_ok=True)
    (paths.home() / "config" / "global.toml").write_text(f'[access]\nteam_domain = "{TEAM}"\naud = "{AUD}"\n')
    fakes.http.script("GET", CERTS, 200, {}, json.dumps({"keys": [rsatest.jwk(key, "k1")]}).encode())
    yield fakes
    access.clear_cache()


def claims(**kw):
    now = int(time.time())
    return {"aud": [AUD], "exp": now + 600, "iat": now, "iss": f"https://{TEAM}", "email": "a@b.c", **kw}


def test_lock_off_by_default(api, fakes):
    assert access.settings() == {"team_domain": "", "aud": "", "on": False}
    assert api("/api/anything", "POST", POST_HEADERS, {})[0] == 404


def test_lock_on_needs_a_token(api, locked):
    status, body = api("/api/anything", "POST", POST_HEADERS, {})
    assert status == 403 and "Cloudflare Access" in body["message"]


def test_lock_on_accepts_a_good_token_and_caches_the_certs(api, locked, key):
    headers = {**POST_HEADERS, "Cf-Access-Jwt-Assertion": rsatest.sign(key, "k1", claims())}
    assert api("/api/anything", "POST", headers, {})[0] == 404
    assert api("/api/anything", "POST", headers, {})[0] == 404
    assert [c["url"] for c in locked.http.calls].count(CERTS) == 1


@pytest.mark.parametrize("change", ["aud", "exp", "iss", "kid", "alg", "sig", "other-key"])
def test_lock_on_refuses_bad_tokens(api, locked, key, change):
    c = claims()
    kid, alg, signer = "k1", "RS256", key
    if change == "aud":
        c["aud"] = ["someone-else"]
    elif change == "exp":
        c["exp"] = int(time.time()) - 120   # past the 30 s leeway
    elif change == "iss":
        c["iss"] = "https://evil.cloudflareaccess.com"
    elif change == "kid":
        kid = "k9"
    elif change == "alg":
        alg = "HS256"
    elif change == "other-key":
        signer = rsatest.make_key(1024)
    token = rsatest.sign(signer, kid, c, alg)
    if change == "sig":
        head, body, sig = token.split(".")
        token = f"{head}.{rsatest.b64(json.dumps({**c, 'email': 'x@y.z'}).encode())}.{sig}"
    status, _ = api("/api/anything", "POST", {**POST_HEADERS, "Cf-Access-Jwt-Assertion": token}, {})
    assert status == 403


def test_lock_certs_refetched_after_an_hour(locked, key, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(access.time, "time", lambda: now[0])
    token = rsatest.sign(key, "k1", claims(exp=5000))
    assert access.verify(token, locked.http) is None
    now[0] += 3599
    assert access.verify(token, locked.http) is None
    now[0] += 2
    assert access.verify(token, locked.http) is None
    assert [c["url"] for c in locked.http.calls].count(CERTS) == 2


def test_lock_certs_unreachable_refuses(api, locked, key):
    locked.http.script("GET", CERTS, 500, {}, b"")
    headers = {**POST_HEADERS, "Cf-Access-Jwt-Assertion": rsatest.sign(key, "k1", claims())}
    status, body = api("/api/anything", "POST", headers, {})
    assert status == 403 and "Cloudflare Access" in body["message"]


def test_lock_only_half_set_is_off_and_doctor_says_so(fakes):
    from phoenix9 import doctor
    (paths.home() / "config").mkdir(parents=True, exist_ok=True)
    (paths.home() / "config" / "global.toml").write_text(f'[access]\nteam_domain = "{TEAM}"\n')
    assert access.settings()["on"] is False
    ok, detail, fix = doctor.check_access(types.SimpleNamespace(ad=fakes))
    assert not ok and "aud" in detail and fix
