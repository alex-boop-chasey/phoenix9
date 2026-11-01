"""Ops for the app as a whole: version info, the Global settings view and the services registry."""
import importlib.util

import phoenix9
from phoenix9 import paths, settings
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
            "reason": reason}


def info() -> dict:
    """Version, update support, GitHub login and feature flags for the dashboard."""
    gh = github.status()
    return {"version": phoenix9.__version__, "update": _update_info(),
            "github": gh, "services": {"supported": True}}


def _default_models() -> dict:
    """{step: {model, fallback_models}} for each AI step, from the library defaults."""
    out = {}
    for step in common.library().steps:
        if step.kind == "ai":
            out[step.name] = {"model": step.ai.get("model", ""),
                              "fallback_models": list(step.ai.get("fallback_models", []))}
    return out


def global_view() -> dict:
    """Global settings (no secret values) and which parts are built yet."""
    values = settings.read_global()
    return {"values": values, "github": github.status(), "default_models": _default_models(),
            "telegram": {"connected": (paths.secrets() / "telegram.env").is_file()},
            "supported": {"services": True, "update": _update_supported(), "secrets": False}}
