"""Start the key proxies a step asks for (step.toml `proxy`) and stop them when the step ends."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from phoenix9 import scrub, services
from phoenix9.library import PROXY_PROJECT
from phoenix9.ops import common as ops_common, services as ops_services

HOST_BIND = "127.0.0.1"
ENV_URL = "PHOENIX_PROXY_"
ENV_TOKEN = "PHOENIX_PROXY_TOKEN_"


def resolve_names(ctx, step) -> list[str]:
    """The service names a step's proxy list means; "@project" = connected store-and-wire ones."""
    names: list[str] = []
    for item in step.proxy:
        if item != PROXY_PROJECT:
            names.append(item)
            continue
        registry = services.read_registry()
        lib = services.load_library()
        for name in ctx.project.settings.get("services", []):
            svc = lib.get(name)
            if svc is None or svc["support"] != "store-and-wire":
                continue
            if registry.get(name, {}).get("connected"):
                names.append(name)
            else:
                ctx.log(f"proxy: {svc['title']} is not connected, so it is left out")
    return list(dict.fromkeys(names))


def _require_connected(name: str) -> None:
    """Fail in plain words before anything runs when the service is not connected."""
    svc = services.get(name)
    title = svc["title"] if svc else name
    if not services.read_registry().get(name, {}).get("connected"):
        raise ops_common.OpsError(f"{title} is not connected in Global settings")


@contextmanager
def step_proxies(ctx, step, bind: str):
    """Start one proxy per service for the step, set ctx.proxies, and always stop them afterwards."""
    handles: dict = {}
    try:
        for name in resolve_names(ctx, step):
            _require_connected(name)
            spec, key = ops_services.proxy_spec_for(name)
            log_path = Path(ctx.run.folder) / "logs" / f"proxy-{name}.jsonl"
            handle = ctx.adapters.proxy.start(spec, key, log_path=log_path, step=step.name, bind=bind)
            handles[name] = handle
            scrub.add_secrets([handle.token])
            ctx.log(f"proxy: started {name} on {bind}:{handle.port}")
        ctx.proxies = {n: {"url": h.url, "token": h.token, "port": h.port, "bind": bind}
                       for n, h in handles.items()}
        yield ctx.proxies
    finally:
        for name, handle in handles.items():
            try:
                handle.stop()
                ctx.log(f"proxy: stopped {name}")
            except Exception as err:     # one proxy failing to stop must not leave the others running
                ctx.log(f"proxy: could not stop {name}: {type(err).__name__}")


def container_env(proxies: dict) -> dict:
    """The env vars a container gets for its proxies (url and token per service)."""
    env = {}
    for name, p in proxies.items():
        tag = name.upper().replace("-", "_")
        env[ENV_URL + tag] = p["url"]
        env[ENV_TOKEN + tag] = p["token"]
    return env


def write_allow_file(ctx, proxies: dict) -> Path | None:
    """Write proxy-allow-<step>.txt (one `IP PORT` line per proxy) in the run folder; None if no proxies."""
    if not proxies:
        return None
    path = Path(ctx.run.folder) / f"proxy-allow-{ctx.step.name}.txt"
    path.write_text("".join(f"{p['bind']} {p['port']}\n" for p in proxies.values()), encoding="utf-8")
    return path
