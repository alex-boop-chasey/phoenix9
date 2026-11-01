"""The vps-docker deployer: builds the project's Dockerfile and runs it as a site container on this server."""
import re

from phoenix9.deploy import DeployError

BUILD_TIMEOUT = 1800
DOCKER_TIMEOUT = 120
LOG_OPTS = ("--log-opt", "max-size=10m", "--log-opt", "max-file=3")
SAFE = re.compile(r"[^a-z0-9._-]+")


# ---------- names and settings ----------
def _commit7(dctx) -> str:
    return (dctx.commit or "")[:7] or "local"


def image_name(dctx, tag: str) -> str:
    """phoenix-site-<project>:<tag>."""
    return f"phoenix-site-{dctx.project.name}:{tag}"


def container_name(dctx, kind: str) -> str:
    """site-<project>-<live|check|preview>."""
    return f"site-{dctx.project.name}-{kind}"


def ports(settings: dict) -> tuple[int, int, int]:
    """(live, side, preview) ports with the defaults filled in; DeployError when missing, out of range or not distinct."""
    live = settings["live_port"]
    if not live:
        raise DeployError("vps-docker needs live_port: the port the tunnel points at")
    side = settings["side_port"] or live + 1000
    preview = settings["preview_port"] or live + 2000
    for name, port in (("live_port", live), ("side_port", side), ("preview_port", preview)):
        if not 1024 <= port <= 65535:
            raise DeployError(f"vps-docker: {name} {port} must be between 1024 and 65535")
    if len({live, side, preview}) != 3:
        raise DeployError(f"vps-docker: live_port, side_port and preview_port must all differ ({live}, {side}, {preview})")
    return live, side, preview


# ---------- docker through the host adapter ----------
def _docker(dctx, *args, timeout=DOCKER_TIMEOUT, cwd=None) -> tuple[int, str, str]:
    dctx.log("docker " + " ".join(args))
    return dctx.adapters.host.run(["docker", *args], timeout=timeout, cwd=cwd)


def _build(dctx, image: str) -> None:
    dockerfile = dctx.source_dir / dctx.settings["dockerfile"]
    if not dockerfile.is_file():
        raise DeployError("vps-docker needs a Dockerfile at the repo root")
    rc, _, err = _docker(dctx, "build", "-f", str(dockerfile), "-t", image, str(dctx.source_dir), timeout=BUILD_TIMEOUT)
    if rc != 0:
        raise DeployError(f"docker build failed: {err.strip()[-300:]}")


def _remove(dctx, name: str) -> None:
    """Stop and remove a container; it is fine if it was not there."""
    _docker(dctx, "stop", name)
    _docker(dctx, "rm", name)


def _run(dctx, name: str, image: str, port: int, restart: bool) -> None:
    argv = ["run", "-d", "--name", name]
    if restart:
        argv += ["--restart", "unless-stopped"]
    argv += ["--memory", dctx.settings["memory"], "--cpus", dctx.settings["cpus"], *LOG_OPTS]
    if dctx.env_file:
        argv += ["--env-file", str(dctx.env_file)]
    argv += ["-p", f"127.0.0.1:{port}:{dctx.settings['container_port']}",
             "--label", f"phoenix9.project={dctx.project.name}", "--label", f"phoenix9.commit={dctx.commit}", image]
    rc, _, err = _docker(dctx, *argv)
    if rc != 0:
        raise DeployError(f"docker run of {name} failed: {err.strip()[-300:]}")


def _image_of(dctx, name: str) -> str:
    """The image a container runs, or '' when there is no such container."""
    rc, out, _ = _docker(dctx, "inspect", "--format", "{{.Config.Image}}", name)
    return out.strip() if rc == 0 else ""


# ---------- health ----------
def _get(dctx, port: int) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}{dctx.settings['health_path']}"
    try:
        status = dctx.adapters.http.request("GET", url, timeout=10)[0]
    except Exception as err:
        return False, f"{type(err).__name__}: {err}"
    return 200 <= status < 400, f"HTTP {status}"


def _wait_healthy(dctx, port: int) -> tuple[bool, str]:
    """Check a port up to [health] tries, pausing between tries on the clock."""
    health = dctx.deployer["health"]
    tries, pause = health["tries"], health["timeout_s"] / health["tries"]
    why = "no check ran"
    for n in range(tries):
        ok, why = _get(dctx, port)
        if ok:
            return True, why
        if n < tries - 1:
            dctx.adapters.clock.sleep(pause)
    return False, why


# ---------- the deployer functions ----------
def deploy(dctx) -> dict:
    """Build, check the new version on the side port, then switch the live container to it."""
    live, side, _ = ports(dctx.settings)
    image = image_name(dctx, _commit7(dctx))
    _build(dctx, image)
    check, site = container_name(dctx, "check"), container_name(dctx, "live")
    _remove(dctx, check)
    _run(dctx, check, image, side, restart=False)
    ok, why = _wait_healthy(dctx, side)
    if not ok:
        _remove(dctx, check)
        raise DeployError(f"new version failed its health check before the switch; the live site was not touched ({why})")
    previous_image = _image_of(dctx, site)
    _remove(dctx, check)
    _remove(dctx, site)
    _run(dctx, site, image, live, restart=True)
    local = f"http://127.0.0.1:{live}/"
    return {"target": f"127.0.0.1:{live}", "url": dctx.settings["public_url"] or local, "version": _commit7(dctx),
            "details": {"image": image, "previous_image": previous_image}}


def health(dctx, result) -> tuple[bool, str]:
    """GET the health path on the live port (or the preview port for a preview)."""
    port = (result.get("details") or {}).get("port") or ports(dctx.settings)[0]
    return _get(dctx, port)


def rollback(dctx, result, previous) -> dict:
    """Put the previous image back as the live container; {restored: None} when there is none."""
    live = ports(dctx.settings)[0]
    site = container_name(dctx, "live")
    image = ((result or {}).get("details") or {}).get("previous_image") \
        or ((previous or {}).get("details") or {}).get("image")
    if not image and (previous or {}).get("version"):
        image = image_name(dctx, previous["version"])          # records keep the version, which is the image tag
    if not image:
        _remove(dctx, site)
        return {"restored": None}
    if _image_of(dctx, site) != image:
        _remove(dctx, site)
        _run(dctx, site, image, live, restart=True)
    ok, _ = _wait_healthy(dctx, live)
    return {"restored": image, "healthy": ok}


def preview(dctx) -> dict:
    """Build the run's worktree and run it as the preview container on the preview port."""
    _, _, port = ports(dctx.settings)
    tag = "preview-" + (SAFE.sub("-", str(dctx.run_id or _commit7(dctx)).lower()).strip("-") or "run")
    image = image_name(dctx, tag)
    _build(dctx, image)
    name = container_name(dctx, "preview")
    _remove(dctx, name)
    _run(dctx, name, image, port, restart=False)
    ok, why = _wait_healthy(dctx, port)
    if not ok:
        _remove(dctx, name)
        raise DeployError(f"the preview failed its health check ({why})")
    local = f"http://127.0.0.1:{port}/"
    return {"target": f"127.0.0.1:{port}", "url": dctx.settings["preview_url"] or local, "version": _commit7(dctx),
            "details": {"image": image, "port": port}}


def stop_preview(dctx, record) -> None:
    """Stop and remove the preview container."""
    _remove(dctx, container_name(dctx, "preview"))
