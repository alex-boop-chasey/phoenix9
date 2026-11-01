"""The deployers runner: loads deployers/<name>, deploys, checks health, rolls back, records every attempt."""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from phoenix9 import events, git, keys, library, paths, scrub, settings
from phoenix9.library import Field

NONE = "none"
FIELDS = [Field("name", str, required=True), Field("title", str, required=True),
          Field("description", str, default=""), Field("supported", bool, default=True),
          Field("proxy_service", str, default=""), Field("preview", bool, default=False),
          Field("for_profiles", list, default=[], list_of=str),
          Field("required_settings", list, default=[], list_of=str),
          Field("settings", dict, default={}), Field("health", dict, default={})]
HEALTH_FIELDS = [Field("timeout_s", int, default=60), Field("tries", int, default=5)]
NEEDED = ("health", "rollback")


class DeployError(Exception):
    """A deploy failed; the message is the plain-words reason."""


@dataclass
class ProjectRef:
    """The project a deploy is for."""
    name: str
    folder: Path
    settings: dict


@dataclass
class DeployContext:
    """Everything a deployer's functions get (never the Docker socket, never account keys)."""
    project: ProjectRef
    deployer: dict
    settings: dict
    source_dir: Path
    commit: str
    run_id: str | None
    adapters: Any
    proxy: dict | None
    env_file: Path | None
    log_path: Path
    log: Callable[[str], None] = field(default=lambda text: None)


# ---------- the library ----------
def _parse(data: dict, folder: Path, where: str):
    """Check one deployer.toml; returns (deployer dict or None, problems)."""
    values, problems = library.check_fields(data, FIELDS, where)
    if values["name"] != folder.name:
        problems.append(f"{where}: name '{values['name']}' must match the folder name '{folder.name}'")
    health, bad = library.check_fields(values["health"], HEALTH_FIELDS, f"{where} [health]")
    problems += bad
    if not bad and (health["tries"] < 1 or health["timeout_s"] < 0):
        problems.append(f"{where} [health]: tries must be 1 or more and timeout_s 0 or more")
    for key in values["required_settings"]:
        if key not in values["settings"]:
            problems.append(f"{where}: required setting '{key}' is not in [settings]")
    values["health"] = health
    values["folder"] = str(folder)
    return (None if problems else values), problems


def _root(root=None) -> Path:
    return Path(root) if root else paths.library() / "deployers"


def load_library(root=None) -> dict:
    """Every deployer by name; a broken deployer.toml is left out (see load_problems)."""
    return {d["name"]: d for d in library.load_folders(_root(root), "deployer.toml", _parse)[0]}


def load_problems(root=None) -> list[str]:
    """Plain-words problems found in the deployers folder."""
    return library.load_folders(_root(root), "deployer.toml", _parse)[1]


def get(name: str) -> dict | None:
    """One deployer, or None when the library has none by that name."""
    return load_library().get(name)


def load_module(deployer: dict):
    """Import the deployer's deploy.py; DeployError when it is missing a health check or a rollback."""
    path = Path(deployer["folder"]) / "deploy.py"
    if not path.is_file():
        raise DeployError(f"{deployer['title']} has no deploy.py")
    spec = importlib.util.spec_from_file_location(f"phoenix9_deployer_{deployer['name'].replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not all(callable(getattr(module, n, None)) for n in NEEDED) or not callable(getattr(module, "deploy", None)):
        raise DeployError(f"{deployer['title']} is refused: every deployer needs a health check and a rollback")
    return module


# ---------- settings ----------
def merge_settings(deployer: dict, given: Any, where: str = "phoenix.toml [deploy.settings]") -> tuple[dict, list[str]]:
    """Deployer defaults overlaid with the project's [deploy.settings]; returns (values, problems)."""
    if not isinstance(given, dict):
        return dict(deployer["settings"]), [f"{where}: must be a table"]
    problems = []
    values = dict(deployer["settings"])
    for key, value in given.items():
        if key not in deployer["settings"]:
            problems.append(f"{where}: unknown key '{key}' for {deployer['title']}")
        elif not library._is_type(value, type(deployer["settings"][key])):
            problems.append(f"{where}: '{key}' must be {library._type_name(type(deployer['settings'][key]))}")
        else:
            values[key] = value
    for key in deployer["required_settings"]:
        if values.get(key) in (0, "", None, []) and not problems:
            problems.append(f"{where}: '{key}' must be set for {deployer['title']}")
    return values, problems


def settings_problems(data: dict, where: str = "phoenix.toml") -> list[str]:
    """Problems with deploy.with and deploy.settings in a project's phoenix.toml data."""
    table = data.get("deploy", {})
    name = table.get("with", settings.PROJECT_SCHEMA["deploy.with"].default)
    if not isinstance(name, str):
        return []
    deployer = load_library().get(name)
    if deployer is None:
        if name == NONE:
            return []
        known = ", ".join(sorted(load_library())) or "none"
        return [f"{where}: deploy.with '{name}' is not a deployer. Available: {known}"]
    if not deployer["supported"] and not table.get("settings"):
        return []
    return merge_settings(deployer, table.get("settings", {}), f"{where} [deploy.settings]")[1]


# ---------- records ----------
def records_path(project: str) -> Path:
    """<project>/.phoenix/deploys.jsonl."""
    return paths.projects() / project / ".phoenix" / "deploys.jsonl"


def read_records(project: str) -> list[dict]:
    """Every deploy record, oldest first; damaged lines are skipped."""
    out = []
    try:
        lines = records_path(project).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def last_good(project: str) -> dict | None:
    """The latest successful non-preview record, or None."""
    for record in reversed(read_records(project)):
        if record.get("ok") and record.get("kind") == "deploy":
            return record
    return None


def _write_record(project: str, record: dict) -> None:
    path = records_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(scrub.scrub(json.dumps(record)) + "\n")


# ---------- one attempt ----------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_path(project: str, run_id: str | None) -> Path:
    if run_id:
        return paths.runs(project) / run_id / "logs" / "deploy.log"
    return paths.logs() / f"deploy-{project}.log"


def _logger(path: Path) -> Callable[[str], None]:
    def log(text: str) -> None:
        """Add scrubbed lines to the deploy log."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for line in str(text).splitlines() or [""]:
                f.write(scrub.scrub(line) + "\n")
    return log


def _reason(err: Exception) -> str:
    text = str(err) if isinstance(err, DeployError) else f"{type(err).__name__}: {err}"
    return scrub.scrub(text)[:500]


def _check_health(module, dctx: DeployContext, result: dict) -> tuple[bool, str]:
    """Run health() up to [health] tries, waiting timeout_s / tries between tries on the clock."""
    health = dctx.deployer["health"]
    tries, pause = health["tries"], health["timeout_s"] / health["tries"]
    why = "no health check ran"
    for n in range(tries):
        try:
            ok, why = module.health(dctx, result)
        except Exception as err:
            ok, why = False, _reason(err)
        dctx.log(f"health try {n + 1}/{tries}: {'ok' if ok else 'not yet'}: {why}")
        if ok:
            return True, why
        if n < tries - 1:
            dctx.adapters.clock.sleep(pause)
    return False, why


def _proxy_info(handle) -> dict:
    return {"url": handle.url, "token": handle.token}


def _start_proxy(adapters, service: str):
    """Start the deployer's service proxy on 127.0.0.1; returns (handle, error words)."""
    from phoenix9.ops import services as ops_services
    from phoenix9.ops.common import OpsError
    try:
        spec, key = ops_services.proxy_spec_for(service)
    except OpsError as err:
        return None, str(err)
    return adapters.proxy.start(spec, key, log_path=paths.logs() / "proxy-deploy.jsonl",
                                step="deploy", bind="127.0.0.1"), ""


def _attempt(adapters, project: str, deployer: dict, module, *, who, run_id, commit, source_dir, kind) -> dict:
    """Deploy (or preview), check health, roll back a failed deploy; returns the record."""
    folder = paths.projects() / project
    data = settings.load_project(folder)
    merged, bad = merge_settings(deployer, data.get("deploy", {}).get("settings", {}))
    record = {"at": _now(), "deployer": deployer["name"], "commit": commit, "version": "", "url": "", "ok": False,
              "rolled_back": False, "reason": "", "who": who, "run": run_id, "kind": kind}
    if bad:
        record["reason"] = "; ".join(bad)
        return record
    previous = last_good(project)
    scrub.add_secrets(keys.secret_values(project))     # so nothing the deployer logs can carry a key
    handle = None
    try:
        if deployer["proxy_service"]:
            handle, error = _start_proxy(adapters, deployer["proxy_service"])
            if handle is None:
                record["reason"] = error
                return record
        with keys.env_file(project) as env_path:
            log_path = _log_path(project, run_id)
            dctx = DeployContext(project=ProjectRef(project, folder, data), deployer=deployer, settings=merged,
                                 source_dir=source_dir, commit=commit, run_id=run_id, adapters=adapters,
                                 proxy=_proxy_info(handle) if handle else None, env_file=env_path,
                                 log_path=log_path, log=_logger(log_path))
            _run_module(module, dctx, previous, record)
    finally:
        if handle:
            handle.stop()
    return record


def _run_module(module, dctx: DeployContext, previous, record: dict) -> None:
    """Call deploy/preview, then health; on failure roll a deploy back. Fills in the record."""
    kind = record["kind"]
    result: dict | None = None
    try:
        call = module.deploy if kind == "deploy" else module.preview
        result = call(dctx) or {}
        record["url"], record["version"] = result.get("url", ""), result.get("version", "")
        ok, why = _check_health(module, dctx, result)
        record["ok"], record["reason"] = ok, ("" if ok else f"health check failed: {why}")
    except Exception as err:
        record["reason"] = _reason(err)
        dctx.log(f"deploy failed: {record['reason']}")
    if record["ok"]:
        return
    if kind == "deploy":
        _roll_back(module, dctx, result, previous, record)
    elif hasattr(module, "stop_preview") and result:
        try:
            module.stop_preview(dctx, {**record, **result})
        except Exception as err:
            dctx.log(f"stopping the failed preview did not work: {_reason(err)}")


def _roll_back(module, dctx: DeployContext, result, previous, record: dict) -> None:
    """Roll the live site back to the last good deploy; says so in the record."""
    try:
        back = module.rollback(dctx, result or {}, previous) or {}
        record["rolled_back"] = True
        record["url"] = back.get("url") or (previous or {}).get("url", "")
        record["version"] = back.get("version") or (previous or {}).get("version", "")
        dctx.log("rolled back to the last good deploy")
    except Exception as err:
        record["reason"] += f"; rollback failed: {_reason(err)}"
        dctx.log(f"rollback failed: {_reason(err)}")


def _finish(adapters, project: str, deployer: dict, record: dict, who: str) -> None:
    """Record the attempt: deploys.jsonl, event, changelog line and notify message."""
    from phoenix9.ops import common
    _write_record(project, record)
    events.emit("deploy.finished", project=project, run=record["run"], ok=record["ok"],
                rolled_back=record["rolled_back"], url=record["url"], deployer=deployer["name"],
                reason=record["reason"])
    what = "Preview" if record["kind"] == "preview" else "Deploy"
    short = (record["commit"] or "")[:7] or "latest"
    if record["ok"]:
        words = f"{'Previewed' if what == 'Preview' else 'Deployed'} {short} to {record['url']} with {deployer['name']}"
    elif record["rolled_back"]:
        words = f"Deploy failed, rolled back: {record['reason']}"
    else:
        words = f"{what} failed: {record['reason']}"
    common._append_changelog(project, who, words)
    adapters.notify.send(scrub.scrub(f"{project}: {words}" + (f" ({record['url']})" if record["ok"] and record["url"] else "")))


def _prepare(project: str, kind: str):
    """(deployer, module, early result): the early result is set when there is nothing to run."""
    folder = paths.projects() / project
    try:
        data = settings.load_project(folder)
    except settings.SettingsError as err:
        return None, None, {"ok": False, "reason": str(err)}
    name = data.get("deploy", {}).get("with", settings.PROJECT_SCHEMA["deploy.with"].default)
    if name == NONE:
        return None, None, {"ok": True, "skipped": "deployer none"}
    deployer = get(name)
    if deployer is None:
        return None, None, {"ok": False, "reason": f"'{name}' is not a deployer"}
    if not deployer["supported"]:
        return None, None, {"ok": False, "reason": f"{deployer['title']} is not yet supported"}
    if kind == "preview" and not deployer["preview"]:
        return None, None, {"ok": False, "reason": f"{deployer['title']} cannot deploy a preview"}
    try:
        module = load_module(deployer)
    except DeployError as err:
        return None, None, {"ok": False, "reason": str(err)}
    except Exception as err:
        return None, None, {"ok": False, "reason": f"{deployer['title']} could not be loaded: {_reason(err)}"}
    return deployer, module, None


def _commit_of(source_dir: Path, commit: str | None) -> str:
    if commit:
        return commit
    try:
        return git.head(source_dir)
    except Exception:
        return ""


def _go(adapters, project, kind, *, who, run_id, commit, source_dir) -> dict:
    deployer, module, early = _prepare(project, kind)
    if early is not None:
        return early
    commit = _commit_of(source_dir, commit)
    record = _attempt(adapters, project, deployer, module, who=who, run_id=run_id, commit=commit,
                      source_dir=source_dir, kind=kind)
    _finish(adapters, project, deployer, record, who)
    return record


def run_deploy(adapters, project: str, *, who: str, run_id: str | None = None, commit: str | None = None) -> dict:
    """Deploy the project's main code with its deployer, check health, roll back if needed; returns the record."""
    return _go(adapters, project, "deploy", who=who, run_id=run_id, commit=commit,
               source_dir=paths.projects() / project / "code")


def run_preview(adapters, project: str, *, who: str, run_id: str, commit: str | None = None,
                source_dir: Path | None = None) -> dict:
    """Deploy a branch preview from a run's worktree; the live site is untouched, so nothing is rolled back."""
    return _go(adapters, project, "preview", who=who, run_id=run_id, commit=commit,
               source_dir=source_dir or paths.work(project, run_id))


def stop_preview(adapters, project: str, *, who: str, run_id: str) -> dict:
    """Stop the latest running preview of a run."""
    deployer, module, early = _prepare(project, "preview")
    if early is not None:
        return early
    found = [r for r in read_records(project) if r.get("kind") == "preview" and r.get("run") == run_id]
    if not found or not found[-1].get("ok"):
        return {"ok": False, "reason": "there is no running preview for this run"}
    if not callable(getattr(module, "stop_preview", None)):
        return {"ok": False, "reason": f"{deployer['title']} cannot stop a preview"}
    data = settings.load_project(paths.projects() / project)
    merged, _ = merge_settings(deployer, data.get("deploy", {}).get("settings", {}))
    log_path = _log_path(project, run_id)
    dctx = DeployContext(project=ProjectRef(project, paths.projects() / project, data), deployer=deployer,
                         settings=merged, source_dir=paths.work(project, run_id), commit=found[-1]["commit"],
                         run_id=run_id, adapters=adapters, proxy=None, env_file=None, log_path=log_path,
                         log=_logger(log_path))
    try:
        module.stop_preview(dctx, found[-1])
    except Exception as err:
        return {"ok": False, "reason": _reason(err)}
    record = {**found[-1], "at": _now(), "ok": False, "reason": "preview stopped", "who": who}
    _write_record(project, record)
    return {"ok": True, "stopped": True, "run": run_id}
