"""Dashboard addresses: where the dashboard lives, which page origins may change things, and the VS Code address.

They live in HOME/config/global.toml `[dashboard]` (`dashboard_url`, `allowed_origins`, `vscode_url`), with
defaults when absent. The API reads its allowed origins from PHOENIX_API_ORIGINS in HOME/config/api.env when
that is set (save() keeps it in step with the setting), else from the setting itself. Nothing else in Phoenix
holds a hard-coded address (docs/architecture.md section 5.5).
"""
import hashlib
import re
from urllib.parse import urlsplit

from phoenix9 import atomic, paths, settings, tomlw

DEFAULT_DASHBOARD_URL = "https://phoenix.rebirthwebdesign.com.au/"
KEYS = ("dashboard_url", "allowed_origins", "vscode_url")
ENV_KEY = "PHOENIX_API_ORIGINS"
VSCODE_NOT_SET = "Set the VS Code address in Global settings."


class AddressError(ValueError):
    """A bad address, in plain words naming the setting."""


HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})(?:\.[a-z0-9](?:[a-z0-9-]{0,62}))*\.?")
DEFAULT_PORTS = {"http": 80, "https": 443}


def origins_digest(origins) -> str:
    """A short digest of a list of page origins (order and repeats ignored): /api/health reports this instead of
    the origins themselves, and the doctor compares it with the digest of the allowed_origins setting."""
    text = "\n".join(sorted({str(o) for o in origins}))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _host_ok(parts) -> bool:
    """True for a plain host name, an IPv4 address or a bracketed IPv6 address (no quotes, *, %, spaces)."""
    host = parts.hostname or ""
    if "[" in parts.netloc:                       # IPv6: [hex and colons (and dots for a v4 tail)]
        return bool(re.fullmatch(r"[0-9a-f:.]+", host)) and ":" in host
    return bool(HOST_RE.fullmatch(host))


def _url(key: str, text) -> str:
    """A checked http(s) address (stripped); AddressError otherwise."""
    if not isinstance(text, str) or not text.strip():
        raise AddressError(f"'{key}' needs an address like https://phoenix.example.com/")
    text = text.strip()
    parts = urlsplit(text)
    bad = AddressError(f"'{key}' must be an http or https address, not {text!r}")
    if parts.scheme not in ("http", "https") or not parts.hostname or re.search(r"\s", text):
        raise bad
    if not _host_ok(parts):
        raise AddressError(f"'{key}' has a host name Phoenix can't use in {text!r}: only letters, digits, dots "
                           "and dashes (or an IP address) are allowed, no quotes, *, % or spaces")
    try:
        parts.port
    except ValueError:
        raise AddressError(f"'{key}' has a port that isn't a number from 1 to 65535 in {text!r}") from None
    return text


def origin_of(url: str, key: str = "dashboard_url") -> str:
    """The origin (scheme://host[:port]) of an address, exactly the form a browser sends in its Origin header:
    lower-case host, IPv6 kept in brackets, and no port when it is the scheme's default (:443, :80)."""
    if isinstance(url, str) and url.strip().lower() in ("null", "*"):
        raise AddressError(f"'{key}' can't be {url.strip()!r}: name the real address the dashboard is opened from")
    parts = urlsplit(_url(key, url))
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port and parts.port != DEFAULT_PORTS[parts.scheme] else ""
    return f"{parts.scheme}://{host}{port}"


def check_reachable(origins: list[str], dashboard_url: str, own_origin: str | None = None) -> None:
    """Refuse an allowed-origins list that would lock the dashboard out: it must hold the dashboard address's
    origin and (for a change made from a page) that page's own origin."""
    need = origin_of(dashboard_url)
    if need not in origins:
        raise AddressError(f"The allowed origins must include the dashboard's own address, {need}, or the "
                           "dashboard couldn't change anything any more. Add it to the list (or change the "
                           "dashboard address first).")
    if own_origin and own_origin not in origins:
        raise AddressError(f"The allowed origins must include {own_origin}, the address this page is open on, "
                           "or saving would lock this page out. Add it to the list, or make the change from "
                           "the dashboard's own address.")


def _table() -> dict:
    table = settings.read_global().get("dashboard")
    return table if isinstance(table, dict) else {}


def read() -> dict:
    """{dashboard_url, allowed_origins, vscode_url} from global.toml, defaults filled in
    (allowed_origins defaults to the dashboard address's origin; vscode_url to empty = not set)."""
    table = _table()
    url = table.get("dashboard_url") if isinstance(table.get("dashboard_url"), str) and table["dashboard_url"] else ""
    url = url or DEFAULT_DASHBOARD_URL
    origins = table.get("allowed_origins")
    if not isinstance(origins, list) or not all(isinstance(o, str) for o in origins) or not origins:
        try:
            origins = [origin_of(url)]
        except AddressError:
            origins = [origin_of(DEFAULT_DASHBOARD_URL)]
    vscode = table.get("vscode_url") if isinstance(table.get("vscode_url"), str) else ""
    return {"dashboard_url": url, "allowed_origins": list(origins), "vscode_url": vscode.strip()}


def check(changes: dict) -> dict:
    """Check and tidy the given keys (unknown keys refused); allowed_origins may be a list or a comma list."""
    out = {}
    for key, value in changes.items():
        if key not in KEYS:
            raise AddressError(f"'{key}' is not a dashboard address setting. Use one of: {', '.join(KEYS)}.")
        if key == "dashboard_url":
            out[key] = _url(key, value)
        elif key == "vscode_url":
            out[key] = "" if value is None or (isinstance(value, str) and not value.strip()) else _url(key, value)
        else:
            items = value.split(",") if isinstance(value, str) else value
            if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
                raise AddressError("'allowed_origins' must be a list of addresses")
            origins = list(dict.fromkeys(origin_of(i, key) for i in items if i.strip()))
            if not origins:
                raise AddressError("'allowed_origins' needs at least one address, or the dashboard can't change anything")
            out[key] = origins
    return out


def api_env_path():
    """HOME/config/api.env (the API unit's environment file)."""
    return paths.config() / "api.env"


def api_env_origins() -> list[str]:
    """The origins PHOENIX_API_ORIGINS in api.env lists ([] when the file or the line is missing)."""
    try:
        text = api_env_path().read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(rf"^\s*{ENV_KEY}\s*=\s*['\"]?([^'\"\n]*)", text, re.M)
    return [o.strip() for o in m.group(1).split(",") if o.strip()] if m else []


def write_api_env(origins: list[str]) -> None:
    """Rewrite the PHOENIX_API_ORIGINS line of api.env (other lines, like the port, are kept)."""
    path = api_env_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    line = f"{ENV_KEY}={','.join(origins)}"
    kept = [x for x in lines if not re.match(rf"^\s*{ENV_KEY}\s*=", x)]
    atomic.write_text(path, "\n".join([*kept, line]) + "\n", mode=0o644)


def save(changes: dict, own_origin: str | None = None) -> tuple[dict, bool]:
    """Save checked changes into global.toml [dashboard] and keep api.env in step; returns
    (the new values, True when the allowed origins in api.env changed and the API must restart).
    A result that would lock the dashboard out (check_reachable) is refused and nothing is written;
    `own_origin` is the Origin of the page asking (API), which must stay allowed too."""
    clean = check(changes)
    data = dict(settings.read_global())
    table = dict(data.get("dashboard") if isinstance(data.get("dashboard"), dict) else {})
    before_values = read()
    table.update(clean)
    if "dashboard_url" in clean and "allowed_origins" not in table:
        table["allowed_origins"] = [origin_of(clean["dashboard_url"])]
    if "dashboard_url" in clean or "allowed_origins" in clean:
        url = table.get("dashboard_url") or before_values["dashboard_url"]
        origins = table.get("allowed_origins") or before_values["allowed_origins"]
        check_reachable(origins, url, own_origin)
    data["dashboard"] = table
    tomlw.dump(paths.config() / "global.toml", data)
    values = read()
    before = api_env_origins()
    if before != values["allowed_origins"]:
        write_api_env(values["allowed_origins"])
    return values, before != values["allowed_origins"]


def migrate_once() -> dict | None:
    """One-time move to the address settings: when global.toml has no allowed_origins yet, set it to the origins
    api.env already allows plus the dashboard address's origin. Returns what it did, or None when already done."""
    if "allowed_origins" in _table():
        return None
    kept = []
    for found in api_env_origins():          # an entry Phoenix can't use any more is dropped, not fatal
        try:
            kept.append(origin_of(found, "allowed_origins"))
        except AddressError:
            pass
    origins = list(dict.fromkeys([*kept, origin_of(read()["dashboard_url"])]))
    values, changed = save({"allowed_origins": origins})
    return {"allowed_origins": values["allowed_origins"], "api_env_changed": changed}
