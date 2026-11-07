"""Who may use the API: the uids allowed at the far end (access.peer_uids, default root only), and the
optional Cloudflare Access lock on every route but /api/health: a signed Cf-Access-Jwt-Assertion token (RS256).

It is on only when global.toml has both [access] team_domain and aud. The team's public keys come from
https://<team_domain>/cdn-cgi/access/certs and are kept for an hour. RS256 is checked with the standard
library alone (RSASSA-PKCS1-v1_5 with SHA-256: the signature raised to e mod n must equal the padded digest).
"""
import base64
import hashlib
import hmac
import json
import re
import threading
import time

from phoenix9 import settings as settings_mod

CERTS_TTL_S = 3600
REFETCH_GAP_S = 60          # an unknown key id fetches the certs again, at most this often
LEEWAY_S = 30               # clock difference allowed on exp / nbf
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")   # DER DigestInfo for SHA-256

_cache: dict = {}           # certs url -> (fetched at, {kid: (n, e)})
_lock = threading.Lock()


def settings() -> dict:
    """{team_domain, aud, on}: the [access] table of global.toml; on only when both are set."""
    table = settings_mod.read_global().get("access")
    table = table if isinstance(table, dict) else {}
    team = table.get("team_domain") if isinstance(table.get("team_domain"), str) else ""
    aud = table.get("aud") if isinstance(table.get("aud"), str) else ""
    team, aud = team.strip().lower().removeprefix("https://").rstrip("/"), aud.strip()
    return {"team_domain": team, "aud": aud, "on": bool(team and aud)}


DEFAULT_PEER_UIDS = [0]


def _peer_uids_raw():
    table = settings_mod.read_global().get("access")
    table = table if isinstance(table, dict) else {}
    for key in ("peer_uids", "write_peer_uids"):    # write_peer_uids: the first name for the same setting
        if key in table:
            return key, table[key]
    return None, None


def _peer_uids_ok(value) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(type(u) is int and 0 <= u < 2 ** 32 for u in value))


def peer_uids() -> list[int]:
    """The uids allowed at the far end of an API connection: access.peer_uids in global.toml (the older name
    access.write_peer_uids also works), default [0]. A setting that is not a non-empty list of uids is ignored
    (root only), and the doctor says so."""
    _key, value = _peer_uids_raw()
    return sorted(set(value)) if _peer_uids_ok(value) else list(DEFAULT_PEER_UIDS)


def peer_uids_problem() -> str:
    """'' when access.peer_uids is unset or valid; else what is wrong with it (for the doctor)."""
    key, value = _peer_uids_raw()
    if key is None or _peer_uids_ok(value):
        return ""
    return f"access.{key} is not a list of uids (whole numbers such as [0]), so only root (uid 0) is allowed"


def clear_cache() -> None:
    """Forget the fetched keys (tests, and after a settings change)."""
    with _lock:
        _cache.clear()


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _int(text) -> int:
    return int.from_bytes(_b64(str(text)), "big")


def _fetch(url: str, http) -> dict:
    """{kid: (n, e)} of the RSA keys at the certs url ({} when it cannot be read)."""
    try:
        status, _headers, body = http.request("GET", url, timeout=10)
        data = json.loads(body) if status == 200 else {}
    except Exception:
        return {}
    keys = {}
    for k in data.get("keys", []) if isinstance(data, dict) else []:
        if isinstance(k, dict) and k.get("kty") == "RSA" and isinstance(k.get("kid"), str):
            try:
                keys[k["kid"]] = (_int(k["n"]), _int(k["e"]))
            except (KeyError, ValueError, TypeError):
                continue
    return keys


def _keys(url: str, http, kid: str) -> dict:
    """The cached keys, fetched again when older than an hour (or when kid is new and a minute has gone by)."""
    now = time.time()
    with _lock:
        at, keys = _cache.get(url, (None, {}))
    stale = at is None or now - at >= CERTS_TTL_S or (kid not in keys and now - at >= REFETCH_GAP_S)
    if stale:
        fresh = _fetch(url, http)
        if fresh:
            with _lock:
                _cache[url] = (now, fresh)
            keys = fresh
    return keys


def rs256_ok(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    """True when signature is a valid RSASSA-PKCS1-v1_5 SHA-256 signature of signing_input under (n, e)."""
    k = (n.bit_length() + 7) // 8
    if k < 128 or len(signature) != k:          # 1024-bit keys at least
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(signing_input).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify(token, http, cfg: dict | None = None) -> str | None:
    """None when the token is a valid Access token for this team and aud; else the reason (for the log)."""
    cfg = cfg or settings()
    if not cfg["on"]:
        return None
    if not DOMAIN_RE.match(cfg["team_domain"]):
        return "the access.team_domain setting is not a plain domain"
    if not isinstance(token, str) or token.count(".") != 2:
        return "no Access token"
    head_b64, body_b64, sig_b64 = token.split(".")
    try:
        head, claims, sig = json.loads(_b64(head_b64)), json.loads(_b64(body_b64)), _b64(sig_b64)
    except (ValueError, TypeError):
        return "the Access token cannot be read"
    if not isinstance(head, dict) or not isinstance(claims, dict):
        return "the Access token cannot be read"
    if head.get("alg") != "RS256":
        return "the Access token is not RS256"
    kid = head.get("kid")
    if not isinstance(kid, str):
        return "the Access token names no key"
    url = "https://%s/cdn-cgi/access/certs" % cfg["team_domain"]
    key = _keys(url, http, kid).get(kid)
    if key is None:
        return "the Access token's key is not one of the team's keys (or the keys could not be fetched)"
    if not rs256_ok(("%s.%s" % (head_b64, body_b64)).encode(), sig, *key):
        return "the Access token's signature is wrong"
    now = time.time()
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if cfg["aud"] not in auds:
        return "the Access token is for another application"
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp + LEEWAY_S < now:
        return "the Access token has expired"
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and nbf - LEEWAY_S > now:
        return "the Access token is not valid yet"
    iss = claims.get("iss")
    if iss is not None and iss != "https://%s" % cfg["team_domain"]:
        return "the Access token is from another team"
    return None
