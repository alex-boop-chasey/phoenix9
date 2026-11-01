"""Ops for the app as a whole: version info, the Global settings view and the services registry."""
import importlib.util
import tomllib

import phoenix9
from phoenix9 import paths
from phoenix9.ops import common, github


def _update_supported() -> bool:
    """True only when the update ops module exists (phase 4)."""
    return importlib.util.find_spec("phoenix9.ops.update") is not None


def info() -> dict:
    """Version, update support, GitHub login and feature flags for the dashboard."""
    gh = github.status()
    return {"version": phoenix9.__version__,
            "update": {"supported": _update_supported(), "installed": phoenix9.__version__, "newest": None,
                       "available": False, "can_install": False,
                       "reason": "" if _update_supported() else "Updates arrive in a later version."},
            "github": gh, "services": {"supported": False}}


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
    path = paths.config() / "global.toml"
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        values = {}
    return {"values": values, "github": github.status(), "default_models": _default_models(),
            "telegram": {"connected": (paths.secrets() / "telegram.env").is_file()},
            "supported": {"services": False, "update": _update_supported(), "secrets": False}}


def services_view() -> dict:
    """The services registry; not built until phase 4."""
    return {"supported": False, "services": []}
