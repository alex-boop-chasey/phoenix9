"""Turning Phoenix's own paths into paths on the Docker host.

When Phoenix runs in its own container (deploy/docker-compose.yml), it starts
step containers through the host's Docker socket. Docker then reads every
bind-mount source on the host, not inside the Phoenix container. So a path
like /phoenix/runs/<id>/prompts/x.md must be given to Docker as the place
where the `phoenix-runs` volume really lives on the host, for example
/var/lib/docker/volumes/phoenix-runs/_data/<id>/prompts/x.md.

The mapping is switched on by the PHOENIX_VOLUMES setting in the environment,
for example `plans=phoenix-plans,runs=phoenix-runs,config=phoenix-config,cache=phoenix-cache`.
Each named Phoenix folder is looked up once with `docker volume inspect`.
Without PHOENIX_VOLUMES (development, tests) paths are used as they are.

Phoenix's own read-only files that live in its image and not in a volume
(the hooks folder, the test configs) are copied once into
cache/assets/<fingerprint>/ so Docker can find them on the host too.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from phoenix import config

ENV = "PHOENIX_VOLUMES"
FOLDERS = ("plans", "runs", "config", "cache")
ASSETS = "assets"

# (path inside the Phoenix container, path on the host), longest inside path first
_MAP: list[tuple[Path, Path]] = []
_LOADED = False


class HostPathError(Exception):
    """A path cannot be given to Docker. The message says why, in plain English."""


def enabled() -> bool:
    """True when Phoenix runs in its own container and must map paths."""
    return bool(os.environ.get(ENV, "").strip())


def parse_volumes(text: str) -> dict[str, str]:
    """Read `plans=phoenix-plans,runs=...` into {"plans": "phoenix-plans", ...}."""
    out: dict[str, str] = {}
    for part in text.replace(" ", ",").split(","):
        if not part.strip():
            continue
        folder, sep, volume = part.partition("=")
        folder, volume = folder.strip(), volume.strip()
        if not sep or folder not in FOLDERS or not volume:
            raise HostPathError(f"{ENV} has a bad item {part.strip()!r}: write it as <folder>=<volume>, "
                                f"where <folder> is one of {', '.join(FOLDERS)}.")
        out[folder] = volume
    return out


def docker_volume_mountpoint(volume: str) -> str:
    """Ask Docker where a named volume is stored on the host."""
    r = subprocess.run(["docker", "volume", "inspect", volume], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise HostPathError(f"docker volume inspect {volume} failed: {r.stderr.strip() or r.returncode}")
    try:
        point = json.loads(r.stdout)[0]["Mountpoint"]
    except (ValueError, LookupError, TypeError):
        raise HostPathError(f"docker volume inspect {volume} gave no Mountpoint") from None
    if not point or not point.startswith("/"):
        raise HostPathError(f"docker volume inspect {volume} gave a strange Mountpoint: {point!r}")
    return point


def asset_dirs() -> list[Path]:
    """Phoenix's own folders that step containers mount but that live in the image, not a volume."""
    from phoenix import checks, docker            # late import: docker imports this module
    return [docker.HOOKS_DIR, checks.TESTCONFIG_DIR]


def load(inspect: Callable[[str], str] | None = None) -> list[tuple[Path, Path]]:
    """Build the path mapping once (does nothing when PHOENIX_VOLUMES is not set).

    Each Phoenix folder must be given; the assets are copied into cache/assets/.
    `inspect(volume)` returns a volume's host folder (default: docker volume inspect).
    Returns the mapping as (inside, host) pairs.
    """
    global _LOADED
    _MAP.clear()
    _LOADED = True
    if not enabled():
        return []
    inspect = inspect or docker_volume_mountpoint
    volumes = parse_volumes(os.environ[ENV])
    missing = [f for f in FOLDERS if f not in volumes]
    if missing:
        raise HostPathError(f"{ENV} does not name a volume for: {', '.join(missing)}.")
    p = config.paths().all()
    pairs = [(p[folder].resolve(), Path(inspect(volume))) for folder, volume in volumes.items()]
    for src in asset_dirs():
        if src.is_dir():
            dest = p["cache"] / ASSETS / tree_hash(src) / src.resolve().relative_to("/")
            copy_tree(src, dest)
            pairs.append((src.resolve(), host_of(dest, pairs)))
    _MAP[:] = sorted(pairs, key=lambda pair: len(pair[0].parts), reverse=True)
    return list(_MAP)


def tree_hash(src: Path) -> str:
    """A short fingerprint of a folder's file names and contents."""
    h = hashlib.sha256()
    for f in sorted(p for p in Path(src).rglob("*") if p.is_file()):
        h.update(str(f.relative_to(src)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def copy_tree(src: Path, dest: Path) -> None:
    """Copy the folder src to dest once; an existing copy is never changed.

    dest is named after the contents (tree_hash), so a step container that
    has the copy mounted right now never sees it change or disappear.
    """
    if dest.is_dir():
        return
    tmp = dest.with_name(dest.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, tmp, symlinks=False)
    os.replace(tmp, dest)


def host_of(path: Path, pairs: list[tuple[Path, Path]]) -> Path:
    """Map one path with the given pairs (longest match wins), or raise HostPathError."""
    path = Path(path).resolve()
    for inside, host in sorted(pairs, key=lambda pair: len(pair[0].parts), reverse=True):
        if path == inside or path.is_relative_to(inside):
            return host / path.relative_to(inside)
    raise HostPathError(f"{path} is not inside a Phoenix volume, so a step container cannot mount it.")


def to_host(path: Path) -> Path:
    """Return where `path` is on the Docker host (the same path when not in a container)."""
    if not enabled():
        return Path(path).resolve()
    if not _LOADED:
        load()
    return host_of(path, _MAP)


def reset() -> None:
    """Forget the mapping (tests use this)."""
    global _LOADED
    _MAP.clear()
    _LOADED = False
