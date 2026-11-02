"""Ops for account-level services: list, connect (with a key check), disconnect, recipes, proxy spec."""
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


def _service(name: str) -> dict:
    """One library service; OpsError for an unknown name."""
    svc = services.get(name)
    if svc is None:
        known = ", ".join(sorted(services.load_library())) or "none"
        raise common.OpsError(f"There is no service called '{name}'. Available: {known}.")
    return svc


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
    return {"name": svc["name"], "title": svc["title"], "description": svc["description"],
            "support": svc["support"], "connected": True if only else bool(entry.get("connected", False)),
            "note": "no account connection needed" if only else "",
            "account_keys": list(svc["account_keys"]),
            "checked": "not checked" if only else entry.get("checked", "not checked"),
            "checked_at": entry.get("checked_at", ""),
            "project_keys": [{"name": k["name"], "secret": k["secret"]} for k in svc["project_keys"]],
            "hosts": list(svc["hosts"]), "used_by": used_by(svc["name"])}


def list_() -> list[dict]:
    """Every library service with its connection state (never a value)."""
    registry = services.read_registry()
    return [_row(s, registry) for _, s in sorted(services.load_library().items())]


def _check(svc: dict, key: str, adapters) -> str:
    """Call the service's [check] through a proxy that allows only that call; returns the result words."""
    check = svc["check"]
    rule = proxy.find_rule(proxy.spec_from_service(svc).rules, check["method"], check["path"])
    spec = proxy.spec_from_service(svc)
    spec = proxy.ProxySpec(service=spec.service, upstream=spec.upstream, auth_header=spec.auth_header,
                           auth_format=spec.auth_format, rules=(rule,), extra_headers=spec.extra_headers)
    handle = adapters.proxy.start(spec, key, log_path=paths.logs() / "proxy-services.jsonl",
                                  step="services-connect", bind="127.0.0.1")
    try:
        status, _, _ = adapters.http.request(check["method"], handle.url + check["path"],
                                             headers={TOKEN_HEADER: handle.token}, timeout=20)
        return "ok" if status in check["expect"] else f"failed: HTTP {status}"
    except Exception as err:   # the check must never break saving the key
        return scrub.scrub(f"failed: {type(err).__name__}")
    finally:
        handle.stop()


def connect(name: str, values: dict, *, who: str, check: bool = True) -> dict:
    """Save a service's account keys, then (unless check is False) try them; a failed check keeps the keys."""
    svc = _service(name)
    if _keys_only(svc):
        raise common.OpsError(f"{svc['title']} needs no account connection; add its keys per project.")
    want, got = set(svc["account_keys"]), set(values)
    if want != got:
        parts = []
        if want - got:
            parts.append("missing " + ", ".join(sorted(want - got)))
        if got - want:
            parts.append("not wanted " + ", ".join(sorted(got - want)))
        raise common.OpsError(f"{svc['title']} needs exactly {', '.join(svc['account_keys'])} ({'; '.join(parts)}).")
    _guard(keys.write_secret_file, svc["secrets_file"], dict(values))
    result = _check(svc, values[svc["proxy"]["key"]], common.make_adapters()) if check else "not checked"
    registry = services.read_registry()
    registry[name] = {"connected": True, "connected_at": _now(), "account_keys": list(svc["account_keys"]),
                      "checked": result, "checked_at": _now() if check else ""}
    services.write_registry(registry)
    common.record_command(who, f"services connect {name}")
    if result == "ok":
        message = f"{svc['title']}: connected, key checked OK."
    elif result == "not checked":
        message = f"{svc['title']}: connected, key not checked."
    else:
        message = f"{svc['title']}: saved, but {svc['title']} refused it: {result.removeprefix('failed: ')}."
    return {"name": name, "connected": True, "checked": result, "message": message}


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
    if _keys_only(svc):
        raise common.OpsError(f"{svc['title']} needs no account connection, so it has no proxy.")
    if not services.read_registry().get(name, {}).get("connected"):
        raise common.OpsError(f"{svc['title']} is not connected. Run: phoenix services connect {name}")
    values = _guard(keys.read_secret_file, svc["secrets_file"])
    key = values.get(svc["proxy"]["key"])
    if not key:
        raise common.OpsError(f"The saved {svc['title']} keys have no {svc['proxy']['key']}; connect it again.")
    return proxy.spec_from_service(svc), key
