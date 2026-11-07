"""A tiny test-only RSA key maker and RS256 signer (stdlib), for testing the Cloudflare Access token check."""
import base64
import hashlib
import json
import secrets

SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _probable_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(24):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _probable_prime(c):
            return c


def make_key(bits: int = 1024) -> dict:
    """{n, e, d} of a fresh RSA key (test use only)."""
    e = 65537
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            n = p * q
            if n.bit_length() == bits:
                return {"n": n, "e": e, "d": pow(e, -1, phi)}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_b64(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def jwk(key: dict, kid: str) -> dict:
    """The public half as a JSON Web Key."""
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "n": _int_b64(key["n"]), "e": _int_b64(key["e"])}


def sign(key: dict, kid: str, claims: dict, alg: str = "RS256") -> str:
    """A compact RS256 token over the claims."""
    head = b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signing = f"{head}.{body}".encode()
    k = (key["n"].bit_length() + 7) // 8
    t = SHA256_PREFIX + hashlib.sha256(signing).digest()
    em = b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), key["d"], key["n"]).to_bytes(k, "big")
    return f"{head}.{body}.{b64(sig)}"
