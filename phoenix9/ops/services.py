"""Ops for account-level services: list, connect (with a key check), disconnect, recipes, proxy spec."""
import re
from datetime import datetime, timezone

from phoenix9 import keys, paths, proxy, scrub, services, settings
from phoenix9.ops import common
from phoenix9.proxy import TOKEN_HEADER


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _guard(fn, *args):
    try:
        return fn(*args)
    except keys.KeyError_ as err:
        raise common.OpsError(str(err)) from None


# Phoenix's own account settings that look like services in the dashboard (no proxy, no key check).
BUILTIN = {
    "claude": {"name": "claude", "title": "Claude", "description": "The AI models every build and chat uses.",
               "support": "store-and-wire", "account_keys": ["CLAUDE_CODE_OAUTH_TOKEN"],
               "secrets_file": "claude.env", "project_keys": [], "hosts": [], "proxy": None, "check": None,
               "account_settings": []},
    "telegram": {"name": "telegram", "title": "Telegram",
                 "description": "Messages you when a build finishes or needs you.",
                 "support": "store-and-wire", "account_keys": ["TELEGRAM_BOT_TOKEN"],
                 "secrets_file": "telegram.env", "project_keys": [], "hosts": [], "proxy": None, "check": None,
                 "account_settings": [{"name": "chat_id", "label": "Chat ID", "kind": "text", "options": [],
                                       "default": "", "placeholder": "", "help": ""}]},
}


def _service(name: str) -> dict:
    """One library service (or Claude / Telegram); OpsError for an unknown name."""
    svc = BUILTIN.get(name) or services.get(name)
    if svc is None:
        known = ", ".join(sorted([*services.load_library(), *BUILTIN])) or "none"
        raise common.OpsError(f"There is no service called '{name}'. Available: {known}.")
    return svc


def _is_connected(svc: dict, entry: dict) -> bool:
    """Claude and Telegram count as connected when their key file exists; the rest by the registry."""
    if svc["name"] in BUILTIN:
        return (paths.secrets() / svc["secrets_file"]).is_file()
    return bool(entry.get("connected", False))


def _ends_in(svc: dict) -> dict:
    """{key name: '…abcd'} for each saved account key (the last four characters only; never the value)."""
    try:
        saved = keys.read_secret_file(svc["secrets_file"])
    except keys.KeyError_:
        return {}
    return {k: "…" + v[-4:] for k, v in saved.items() if v and k in svc["account_keys"]}


def _setting_rows(svc: dict, entry: dict) -> list[dict]:
    """The service's plain account settings with their saved (or default) values."""
    saved = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
    return [{**s, "value": saved.get(s["name"], s["default"])} for s in svc["account_settings"]]


def _keys_only(svc: dict) -> bool:
    return svc["support"] == "keys-only"


def used_by(name: str) -> list[str]:
    """Projects whose phoenix.toml lists the service."""
    found = []
    root = paths.projects()
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        try:
            if name in settings.load_project(folder).get("services", []):
                found.append(folder.name)
        except (settings.SettingsError, OSError):
            continue
    return found


def _row(svc: dict, registry: dict) -> dict:
    """One list row (names and flags only)."""
    entry = registry.get(svc["name"], {})
    only = _keys_only(svc)
    connected = True if only else _is_connected(svc, entry)
    return {"name": svc["name"], "title": svc["title"], "description": svc["description"],
            "support": svc["support"], "connected": connected,
            "can_test": bool(svc["check"]),
            "ends_in": {} if only or not connected else _ends_in(svc),
            "account_settings": _setting_rows(svc, entry),
            "note": "no account connection needed" if only else "",
            "account_keys": list(svc["account_keys"]),
            "checked": "not checked" if only else entry.get("checked", "not checked"),
            "checked_at": entry.get("checked_at", ""),
            "project_keys": [{"name": k["name"], "secret": k["secret"], "public": k["public"], "required": k["required"],
                              "help": k["help"]} for k in svc["project_keys"]],
            "hosts": list(svc["hosts"]), "used_by": used_by(svc["name"])}


def list_() -> list[dict]:
    """Every library service with its connection state (never a value)."""
    registry = services.read_registry()
    return [_row(s, registry) for _, s in sorted(services.load_library().items())]


def list_global() -> list[dict]:
    """The rows for Phoenix settings: Claude first, the library services, then Telegram."""
    registry = services.read_registry()
    rows = [_row(BUILTIN["claude"], registry)]
    rows += [_row(s, registry) for _, s in sorted(services.load_library().items())]
    return rows + [_row(BUILTIN["telegram"], registry)]


def _fallback_path(svc: dict, settings_now: dict) -> tuple[str, str]:
    """(fallback path with the saved account settings filled in, plain problem); both empty without a fallback."""
    raw = svc["check"].get("fallback_path", "")
    labels = {x["name"]: x["label"] for x in svc["account_settings"]}
    for name in services.PLACEHOLDER.findall(raw):
        value = settings_now.get(name, "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            return "", f"fill in the {labels.get(name, name)} setting first, so the token can be checked"
    return services.PLACEHOLDER.sub(lambda m: settings_now[m.group(1)], raw), ""


def _try_path(check: dict, path: str, handle, adapters) -> int:
    """Make one check call through the proxy and return the HTTP status."""
    status, _, _ = adapters.http.request(check["method"], handle.url + path,
                                         headers={TOKEN_HEADER: handle.token}, timeout=20)
    return status


def _check(svc: dict, key: str, adapters, settings_now: dict | None = None) -> str:
    """Call the service's [check] (then its fallback_path) through a proxy that allows only those calls."""
    check = svc["check"]
    fallback, missing = _fallback_path(svc, settings_now or {})
    paths_to_try = [check["path"]] + ([fallback] if fallback else [])
    spec = proxy.spec_from_service(svc)
    rules = tuple(proxy.find_rule(spec.rules, check["method"], p) for p in paths_to_try)
    spec = proxy.ProxySpec(service=spec.service, upstream=spec.upstream, auth_header=spec.auth_header,
                           auth_format=spec.auth_format, rules=rules, extra_headers=spec.extra_headers)
    handle = adapters.proxy.start(spec, key, log_path=paths.logs() / "proxy-services.jsonl",
                                  step="services-connect", bind="127.0.0.1")
    try:
        status = _try_path(check, check["path"], handle, adapters)
        if status in check["expect"]:
            return "ok"
        if missing:
            return f"failed: HTTP {status}; {missing}"
        if fallback:
            status = _try_path(check, fallback, handle, adapters)
        return "ok" if status in check["expect"] else f"failed: HTTP {status}"
    except Exception as err:   # the check must never break saving the key
        return scrub.scrub(f"failed: {type(err).__name__}")
    finally:
        handle.stop()


def _check_settings(svc: dict, settings_in: dict) -> dict:
    """The plain account settings to save; OpsError for an unknown name or a choice not on the list."""
    known = {x["name"]: x for x in svc["account_settings"]}
    out = {}
    for key, value in settings_in.items():
        if key not in known:
            raise common.OpsError(f"{svc['title']} has no setting called '{key}'.")
        if not isinstance(value, str):
            raise common.OpsError(f"The {known[key]['label']} setting should be text.")
        if known[key]["kind"] == "select" and value not in known[key]["options"]:
            raise common.OpsError(f"{known[key]['label']} should be one of: {', '.join(known[key]['options'])}.")
        out[key] = value.strip()
    return out


def _check_values(svc: dict, values: dict, was_connected: bool) -> None:
    """The account keys must be exactly the wanted ones (a connected service may send only the ones it replaces)."""
    want, got = set(svc["account_keys"]), {k for k, v in values.items() if v or k not in svc["account_keys"]}
    if was_connected and got <= want:
        return
    parts = []
    if want - got:
        parts.append("missing " + ", ".join(sorted(want - got)))
    if got - want:
        parts.append("not wanted " + ", ".join(sorted(got - want)))
    if parts:
        raise common.OpsError(f"{svc['title']} needs exactly {', '.join(svc['account_keys'])} ({'; '.join(parts)}).")


def connect(name: str, values: dict, *, who: str, check: bool = True, settings_in: dict | None = None) -> dict:
    """Save a service's account keys and settings, then (unless check is False) try them; a failed check keeps them."""
    svc = _service(name)
    if _keys_only(svc):
        raise common.OpsError(f"{svc['title']} needs no account connection; add its keys per project.")
    registry = services.read_registry()
    was = _is_connected(svc, registry.get(name, {}))
    _check_values(svc, values, was)
    extra = _check_settings(svc, settings_in or {})
    values = {k: v for k, v in values.items() if v} if was else dict(values)
    if values:
        saved = _guard(keys.read_secret_file, svc["secrets_file"]) if was else {}
        _guard(keys.write_secret_file, svc["secrets_file"], {**saved, **values})
    key_name = (svc["proxy"] or {}).get("key")
    if check and svc["check"]:
        key = (values or _guard(keys.read_secret_file, svc["secrets_file"])).get(key_name, "")
        result = _check(svc, key, common.make_adapters(), {**(registry.get(name, {}).get("settings") or {}), **extra})
    else:
        result = "not checked"
    old = registry.get(name, {})
    registry[name] = {"connected": True, "connected_at": old.get("connected_at") or _now(),
                      "account_keys": list(svc["account_keys"]), "checked": result,
                      "checked_at": _now() if result != "not checked" else "",
                      "settings": {**(old.get("settings") or {}), **extra}}
    services.write_registry(registry)
    common.record_command(who, f"services connect {name}")
    if result == "ok":
        message = f"{svc['title']}: connected, key checked OK."
    elif result == "not checked":
        message = f"{svc['title']}: connected, key not checked."
    else:
        message = f"{svc['title']}: saved, but {svc['title']} refused it: {result.removeprefix('failed: ')}."
    return {"name": name, "connected": True, "checked": result, "message": message}


def test(name: str, values: dict | None = None, *, who: str) -> dict:
    """Try a service's key (a pasted one, else the saved one) without saving anything; {ok, message}."""
    svc = _service(name)
    if not svc["check"]:
        raise common.OpsError(f"{svc['title']} has no connection test; its key is only saved.")
    values = {k: v for k, v in (values or {}).items() if v}
    key_name = svc["proxy"]["key"]
    key = values.get(key_name) or (_guard(keys.read_secret_file, svc["secrets_file"])
                                   if (paths.secrets() / svc["secrets_file"]).is_file() else {}).get(key_name, "")
    if not key:
        raise common.OpsError(f"Paste the {key_name} first, then test.")
    result = _check(svc, key, common.make_adapters(), services.read_registry().get(name, {}).get("settings") or {})
    common.record_command(who, f"services test {name}")
    ok = result == "ok"
    message = (f"{svc['title']}: the key works." if ok
               else f"{svc['title']} refused the key: {result.removeprefix('failed: ')}.")
    return {"name": name, "ok": ok, "message": message}


def disconnect(name: str, *, who: str, yes: bool = False) -> dict:
    """Forget a service's account keys (needs yes); names projects that still use it."""
    svc = _service(name)
    if _keys_only(svc):
        raise common.OpsError(f"{svc['title']} has no account connection to remove.")
    if not yes:
        raise common.OpsError(f"This removes the saved {svc['title']} account keys. Run it again with --yes.")
    _guard(keys.remove_secret_file, svc["secrets_file"])
    registry = services.read_registry()
    registry.pop(name, None)
    services.write_registry(registry)
    users = used_by(name)
    common.record_command(who, f"services disconnect {name}")
    warning = f"Still used by: {', '.join(users)}." if users else ""
    return {"name": name, "connected": False, "used_by": users, "warning": warning}


def recipes() -> list[dict]:
    """Read-only view of the library: support, install.md, recipe.py, allowed-call count."""
    out = []
    for name, svc in sorted(services.load_library().items()):
        folder = paths.library() / "services" / name
        out.append({"name": name, "title": svc["title"], "support": svc["support"],
                    "install_md": (folder / "install.md").is_file(), "recipe_py": (folder / "recipe.py").is_file(),
                    "allowed_calls": len((svc["proxy"] or {}).get("allow", []))})
    return out


def proxy_spec_for(name: str):
    """(ProxySpec, key) for a connected store-and-wire service; plain error when not connected."""
    svc = _service(name)
    if _keys_only(svc) or not svc["proxy"]:
        raise common.OpsError(f"{svc['title']} needs no account connection, so it has no proxy.")
    if not services.read_registry().get(name, {}).get("connected"):
        raise common.OpsError(f"{svc['title']} is not connected. Run: phoenix services connect {name}")
    values = _guard(keys.read_secret_file, svc["secrets_file"])
    key = values.get(svc["proxy"]["key"])
    if not key:
        raise common.OpsError(f"The saved {svc['title']} keys have no {svc['proxy']['key']}; connect it again.")
    return proxy.spec_from_service(svc), key
