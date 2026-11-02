"""Ops for `phoenix images build`: build the step images that projects use (or all, or only changed ones)."""
from phoenix9 import doctor, paths
from phoenix9.library import read_toml
from phoenix9.ops import common

BASE = "base"
BASE_TAG = "phoenix9-step:base"
LABEL = "phoenix9.commit"


def _all_profiles() -> list[str]:
    root = paths.library() / "profiles"
    return sorted(p.name for p in root.iterdir() if (p / "profile.toml").is_file()) if root.is_dir() else []


def _target(name: str) -> dict:
    """{name, tag, dockerfile, context, watch} for a profile or the base image."""
    lib = paths.library()
    if name == BASE:
        return {"name": BASE, "tag": BASE_TAG, "dockerfile": lib / "image" / "Dockerfile",
                "context": lib / "image", "watch": ["image"]}
    data, _ = read_toml(lib / "profiles" / name / "profile.toml", name)
    return {"name": name, "tag": str((data or {}).get("image") or ""),
            "dockerfile": lib / "profiles" / name / "image" / "Dockerfile", "context": lib,
            "watch": ["image", f"profiles/{name}"]}      # image/ holds scripts every profile copies


def _head(adapters) -> str:
    try:
        done = adapters.git.run_git(paths.library(), "rev-parse", "HEAD", check=False, timeout=15)
        return done.stdout.decode().strip() if done.returncode == 0 else ""
    except Exception:
        return ""


def _changed(adapters, target: dict, head: str) -> bool:
    """True when the image is missing, has no recorded commit, or its files changed since that commit."""
    docker = adapters.docker
    if not target["tag"] or not docker.image_exists(target["tag"]):
        return True
    built = docker.image_label(target["tag"], LABEL)
    if not built or not head:
        return True
    if built == head:
        return False
    try:
        done = adapters.git.run_git(paths.library(), "diff", "--name-only", built, head, "--", *target["watch"],
                                    check=False, timeout=30)
    except Exception:
        return True
    return done.returncode != 0 or bool(done.stdout.strip())


def choose(profiles=(), build_all: bool = False) -> list[str]:
    """Which images to consider: the named ones, all of them, or the profiles existing projects use."""
    known = _all_profiles()
    if build_all:
        return [*known, BASE]
    if profiles:
        unknown = [p for p in profiles if p != BASE and p not in known]
        if unknown:
            raise common.OpsError(f"There is no profile called '{unknown[0]}'. Profiles: {', '.join(known)}.")
        return list(dict.fromkeys(profiles))
    return [p for p in doctor.projects_profiles() if p in known]


def build(profiles=(), build_all: bool = False, changed: bool = False, say=None, adapters=None) -> dict:
    """Build the chosen images; returns {ok, built: [...], skipped: [...]} (ok False when any build failed)."""
    say = say or (lambda line: None)
    adapters = adapters or common.make_adapters()
    head = _head(adapters)
    built, skipped, ok = [], [], True
    for name in choose(profiles, build_all):
        target = _target(name)
        if changed and not _changed(adapters, target, head):
            say(f"{name}: unchanged, skipped")
            skipped.append(name)
            continue
        if not target["tag"] or not target["dockerfile"].is_file():
            say(f"{name}: FAILED (no image tag or Dockerfile)")
            built.append({"profile": name, "tag": target["tag"], "ok": False, "log": ""})
            ok = False
            continue
        log = paths.logs() / f"images-{name}.log"
        say(f"{name}: building {target['tag']} ...")
        rc = adapters.docker.build(target["dockerfile"], target["tag"], target["context"],
                                   {LABEL: head or "unknown"}, log)
        say(f"{name}: {'built' if rc == 0 else f'FAILED (exit {rc}), see {log}'}")
        built.append({"profile": name, "tag": target["tag"], "ok": rc == 0, "log": str(log)})
        ok = ok and rc == 0
    return {"ok": ok, "built": built, "skipped": skipped}
