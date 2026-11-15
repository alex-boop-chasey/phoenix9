"""Key maker: make a project's missing service keys on the host with Alex's saved account keys.

Each service with a maker module (phoenix9/keymakers/) and a [make] block in its service.toml can make
project keys. The module gets `call(method, path, body=None) -> (status, json)`, which goes through a key
proxy that holds ONLY the [make] key and allows ONLY the [make] rules (build containers never get these),
and a plain `ctx` (project name, account settings, the project's non-secret key values). A made value goes
straight into keys.set_key and nowhere else: never into results, events, logs or errors.
"""
import importlib
import json

from phoenix9 import events, keys, paths, project_services, scrub
from phoenix9 import services as service_lib
from phoenix9.ops import common
from phoenix9.proxy import TOKEN_HEADER

# service name -> module name in phoenix9/keymakers/ (tests may put an object with make(call, ctx) here)
PROVIDERS: dict = {}
TIMEOUT = 20
LOG_NAME = "proxy-keymaker.jsonl"
# Pages where a keys-only service's keys are copied by hand (the service.toml website is the fallback).
MANUAL_LINKS = {"clerk": "https://dashboard.clerk.com/last-active?path=api-keys"}


class Refused(Exception):
    """A maker could not make the keys; the message is plain words for Alex (never a value)."""


def _provider(name: str):
    """The maker module for a service, or None when Phoenix cannot make its keys yet."""
    found = PROVIDERS.get(name)
    if isinstance(found, str):
        return importlib.import_module(f"phoenix9.keymakers.{found}")
    return found


def _and(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _missing(svc: dict, have: dict) -> list[str]:
    """The service's required project keys that have no value yet."""
    return [k["name"] for k in svc["project_keys"] if k["required"] and not have.get(k["name"])]


def _maker_key(svc: dict) -> str:
    """The saved [make] key value ('' when it is not saved)."""
    try:
        return keys.read_secret_file(svc["secrets_file"]).get(svc["make"]["key"], "")
    except keys.KeyError_:
        return ""


def _row(svc: dict, have: dict) -> dict:
    """One status row: whether Phoenix can make the service's missing keys, in plain words."""
    title, missing = svc["title"], _missing(svc, have)
    row = {"service": svc["name"], "title": title, "missing": missing, "link": ""}
    if not missing:
        return {**row, "state": "done", "words": f"All the {title} keys are saved."}
    if svc.get("make") and _provider(svc["name"]) is not None:
        if _maker_key(svc):
            return {**row, "state": "ready", "words": f"Phoenix can make {_and(missing)} with your saved {title} key."}
        needs = svc["make"]["needs"] or "make keys"
        return {**row, "state": "needs-account-key", "link": svc["make"]["key_page"],
                "words": f"Save a {title} account key that can {needs} in Settings > Services > {title}."}
    link = MANUAL_LINKS.get(svc["name"]) or svc.get("website", "")
    where = f" from {link}" if link else ""
    words = f"Paste {_and(missing)}{where} into Project > Settings > Keys."
    if svc["name"] not in MANUAL_LINKS:
        words += f" Making {title} keys is manual for now."
    return {**row, "state": "manual", "link": link, "words": words}


def _have(project: str) -> dict:
    """{key name: has a value} for the project's saved keys."""
    return {k["name"]: k["has_value"] for k in keys.list_keys(project)}


def status(project: str) -> list[dict]:
    """Per chosen service: {service, title, state (ready, needs-account-key, manual, done), words, link, missing}."""
    lib, have = service_lib.load_library(), _have(project)
    return [_row(lib[n], have) for n in project_services.chosen(project) if n in lib]


def _ctx(project: str, svc: dict) -> dict:
    """What a maker may know: the project, the account settings and the project's non-secret key values."""
    saved = service_lib.read_registry().get(svc["name"], {}).get("settings") or {}
    settings_now = {s["name"]: saved.get(s["name"], s["default"]) for s in svc["account_settings"]}
    plain = {k["name"]: k["value_if_not_secret"] for k in keys.list_keys(project)
             if not k["secret"] and k["has_value"]}
    return {"project": project, "settings": settings_now, "keys": plain}


def _caller(svc: dict, handle, adapters):
    """call(method, path, body=None) -> (status, json) through the running make proxy; errors are scrubbed."""
    def call(method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {TOKEN_HEADER: handle.token, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            status_code, _, raw = adapters.http.request(method, handle.url + path, headers=headers, body=data,
                                                        timeout=TIMEOUT)
        except Exception as err:
            raise Refused(scrub.scrub(f"{svc['title']} could not be reached ({type(err).__name__}).")) from None
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return status_code, parsed
    return call


def _run_provider(project: str, svc: dict, adapters) -> dict:
    """Start a proxy with only the [make] rules and key, run the maker, always stop the proxy."""
    spec = service_lib.make_spec(svc)
    handle = adapters.proxy.start(spec, _maker_key(svc), log_path=paths.logs() / LOG_NAME, step="keys-make",
                                  bind="127.0.0.1")
    scrub.add_secrets([handle.token])
    try:
        return _provider(svc["name"]).make(_caller(svc, handle, adapters), _ctx(project, svc))
    finally:
        handle.stop()


def _problem(svc: dict, err: Exception) -> str:
    """Plain words for a maker that failed."""
    if isinstance(err, Refused):
        return scrub.scrub(str(err))
    return scrub.scrub(f"{svc['title']}: making the keys failed ({type(err).__name__}).")


def _save(project: str, svc: dict, made: dict) -> list[str]:
    """Save each made value that the service lists and the project has no value for; the names saved."""
    values = {k: v for k, v in made.items() if isinstance(v, str) and v}
    scrub.add_secrets(values.values())
    rows = {k["name"]: k for k in svc["project_keys"]}
    have, saved = _have(project), []
    for name, value in values.items():
        if name not in rows or have.get(name):
            continue
        keys.set_key(project, name, value, secret=rows[name]["secret"])
        saved.append(name)
    return saved


def _one(project: str, svc: dict, adapters) -> tuple[list[str], str, str]:
    """Make one service's keys: (names saved, problem, note)."""
    try:
        made = _run_provider(project, svc, adapters)
        if not isinstance(made, dict):
            raise Refused(f"{svc['title']}: the key maker gave nothing back.")
        note = made.get("note") if isinstance(made.get("note"), str) else ""
        made = {k: v for k, v in made.items() if k != "note"}
        return _save(project, svc, made), "", scrub.scrub(note)
    except Exception as err:     # one service failing never stops the others
        return [], _problem(svc, err), ""


def make(project: str, services: list[str] | None = None, *, who: str) -> dict:
    """Make the missing keys of the ready services (or only those named): {saved, problems, notes, still_missing}."""
    common.project_dir(project)
    rows = {r["service"]: r for r in status(project)}
    wanted = list(dict.fromkeys(services)) if services else \
        [n for n, r in rows.items() if r["state"] == "ready"]
    lib, adapters = service_lib.load_library(), None
    saved, problems, notes = {}, {}, {}
    for name in wanted:
        row = rows.get(name)
        if row is None:
            problems[name] = f"The project does not use a service called '{name}'."
            continue
        if row["state"] != "ready":
            if row["state"] != "done":
                problems[name] = row["words"]
            continue
        adapters = adapters or common.make_adapters()
        names, problem, note = _one(project, lib[name], adapters)
        if names:
            saved[name] = names
        if problem:
            problems[name] = problem
        if note:
            notes[name] = note
    still = [k for r in status(project) for k in r["missing"]]
    events.emit("keys.made", project=project, saved=saved, problems=sorted(problems))
    made_names = [k for names in saved.values() for k in names]
    common.record_command(who, f"project keys {project} make {' '.join(wanted)}".rstrip(), project,
                          change=f"keys made: {', '.join(made_names)}" if made_names else None)
    return {"project": project, "saved": saved, "problems": problems, "notes": notes, "still_missing": still}
