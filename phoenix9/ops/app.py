"""Ops for the app as a whole: version info, the Global settings view and the services registry."""
import importlib.util

import phoenix9
from phoenix9 import addresses, events, git, paths, settings, tomlw
from phoenix9.ops import common, github


def _update_supported() -> bool:
    """True only when the update ops module exists (phase 4)."""
    return importlib.util.find_spec("phoenix9.ops.update") is not None


def _update_info() -> dict:
    """The update panel's facts, from the updater's status (release tags, not the package version)."""
    if not _update_supported():
        return {"supported": False, "installed": phoenix9.__version__, "newest": None, "available": False,
                "can_install": False, "reason": "Updates arrive in a later version."}
    from phoenix9.ops import update
    st = update.status(False)
    installed = (st.get("installed") or {}).get("tag")
    available = bool(st.get("update_available"))
    reason = "" if installed else "Phoenix 9 is not installed yet"
    if installed and st.get("running"):
        reason = "An update is running"
    return {"supported": True, "installed": installed or phoenix9.__version__, "newest": st.get("newest"),
            "available": available, "can_install": bool(available and installed and not st.get("running")),
            "reason": reason, "endpoints": {"install": "update/install", "rollback": "update/rollback"}}


def release_tag() -> str:
    """The release tag of the running copy ('' when it has none or git cannot say)."""
    try:
        done = git.run_git(paths.library(), "describe", "--tags", "--exact-match", check=False, timeout=10)
        return done.stdout.decode(errors="replace").strip() if done.returncode == 0 else ""
    except Exception:
        return ""


def version_label(tag: str = "") -> str:
    """The version as the header shows it: the install tag if known, else 'v' plus major.minor."""
    if tag:
        return tag
    return "v" + ".".join(phoenix9.__version__.split(".")[:2])


def info(tag: str = "") -> dict:
    """Version, update support, GitHub login and feature flags for the dashboard."""
    gh = github.status()
    where = addresses.read()
    return {"version": phoenix9.__version__, "label": version_label(tag), "update": _update_info(),
            "github": gh, "services": {"supported": True}, "dashboard_url": where["dashboard_url"],
            "vscode_url": where["vscode_url"]}


ADDRESS_KEYS = addresses.KEYS


def addresses_view() -> dict:
    """{dashboard_url, allowed_origins, vscode_url} with defaults filled in."""
    return addresses.read()


def migrate_addresses_at_start() -> dict | None:
    """The one-time move to the address settings, run by the API as it starts (no restart: it is starting)."""
    return addresses.migrate_once()


def set_addresses(changes: dict, *, who: str, own_origin: str | None = None) -> dict:
    """Save dashboard addresses (dashboard_url, allowed_origins, vscode_url) in global.toml; when the allowed
    origins change, api.env is rewritten and phoenix-api restarted through the host adapter."""
    from phoenix9.ops import service
    if not changes:
        raise common.OpsError("Say which address to change: " + ", ".join(addresses.KEYS) + ".")
    try:
        values, restart = addresses.save(changes, own_origin=own_origin)
    except addresses.AddressError as err:
        raise common.OpsError(str(err)) from None
    keys = sorted(changes)
    events.emit("settings.changed", project=None, who=who, keys=keys)
    common.record_command(who, "settings global set " + " ".join(keys))
    return {"values": values, "api_restart": _restart_api(restart, service)}


def _restart_api(needed: bool, service) -> str:
    """Ask systemd to restart phoenix-api (without waiting) when needed: 'asked', 'not needed' or 'failed: ...'."""
    if not needed:
        return "not needed"
    done, err = service.restart_unit(common.make_adapters(), "api", no_block=True)
    return "asked" if done else f"failed: {err or 'no reason given'}"


def migrate_addresses(who: str) -> dict:
    """The one-time move to the address settings (allowed origins = api.env's + the dashboard's); restarts the API
    when it changed api.env."""
    from phoenix9.ops import service
    done = addresses.migrate_once()
    if not done:
        return {"migrated": False, "values": addresses.read(), "api_restart": "not needed"}
    common.record_command(who, "settings global migrate")
    return {"migrated": True, "values": addresses.read(), "api_restart": _restart_api(done["api_env_changed"], service)}


def _ai_steps() -> list:
    return [s for s in common.library().steps if s.kind == "ai"]


def default_models() -> dict:
    """{step: {model, fallback_models, title, library}} for each AI step: Phoenix's saved defaults over the library's."""
    saved = settings.global_models()
    out = {}
    for step in _ai_steps():
        lib = {"model": step.ai.get("model", ""), "fallback_models": list(step.ai.get("fallback_models", []))}
        out[step.name] = {**lib, **saved.get(step.name, {}), "title": getattr(step, "title", "") or step.name,
                          "library": lib}
    return out


def set_default_models(steps: dict, *, who: str) -> dict:
    """Save Phoenix's default model (and up to two fallbacks) for AI steps into global.toml [models]."""
    known = {s.name for s in _ai_steps()}
    table = {}
    for name, row in steps.items():
        if name not in known:
            raise common.OpsError(f"'{name}' is not an AI step. Choose from: {', '.join(sorted(known))}.")
        model = row.get("model") if isinstance(row, dict) else None
        fallbacks = row.get("fallback_models", []) if isinstance(row, dict) else None
        if not isinstance(model, str) or not model.strip():
            raise common.OpsError(f"Choose a model for {name}.")
        if not isinstance(fallbacks, list) or not all(isinstance(m, str) and m.strip() for m in fallbacks):
            raise common.OpsError(f"The fallback models for {name} should be a list of model names.")
        chosen = [model.strip(), *[m.strip() for m in fallbacks]]
        if len(set(chosen)) != len(chosen) or len(chosen) > 3:
            raise common.OpsError(f"{name}: use each model once, with at most two fallbacks.")
        table[name] = {"model": chosen[0], "fallback_models": chosen[1:]}
    data = dict(settings.read_global())
    data["models"] = {**(data.get("models") if isinstance(data.get("models"), dict) else {}), **table}
    tomlw.dump(paths.config() / "global.toml", data)
    common.record_command(who, "models set " + ", ".join(sorted(table)))
    return {"saved": sorted(table), "default_models": default_models()}


def global_view() -> dict:
    """Global settings (no secret values) and which parts are built yet."""
    values = settings.read_global()
    return {"values": values, "addresses": addresses.read(), "github": github.status(), "default_models": default_models(),
            "telegram": {"connected": (paths.secrets() / "telegram.env").is_file()},
            "supported": {"services": True, "update": _update_supported(), "secrets": False}}


def write_peer_uid(client, local) -> int | None:
    """The uid of the program at the far end of an API connection (None when it cannot be told), through the
    host adapter."""
    return common.make_adapters().host.socket_uid(client, local)


def access_lock_problem(token) -> str | None:
    """None when the optional Cloudflare Access lock is off or the token is valid; else why it was refused."""
    from phoenix9 import access
    cfg = access.settings()
    if not cfg["on"]:
        return None
    return access.verify(token, common.make_adapters().http, cfg)
