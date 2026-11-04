"""The services library: services/<name>/service.toml (which project keys and hosts each service needs)."""
import re
from pathlib import Path
import tomllib

from phoenix9 import atomic, library, paths, proxy, tomlw
from phoenix9.library import Field

SUPPORTS = ("store-and-wire", "keys-only")
KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
HOST_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
FIELDS = [Field("name", str, required=True), Field("title", str, required=True),
          Field("description", str, default=""), Field("support", str, default="keys-only", choices=SUPPORTS),
          Field("docs", str, default=""), Field("account_keys", list, default=[], list_of=str),
          Field("secrets_file", str, default=""),
          Field("project_keys", list, default=[], list_of=dict), Field("hosts", list, default=[], list_of=str),
          Field("proxy", dict, default=None), Field("check", dict, default=None),
          Field("account_settings", list, default=[], list_of=dict)]
SETTING_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
SETTING_FIELDS = [Field("name", str, required=True), Field("label", str, required=True),
                  Field("kind", str, default="text", choices=("text", "select")),
                  Field("options", list, default=[], list_of=str), Field("default", str, default=""),
                  Field("placeholder", str, default=""), Field("help", str, default="")]
KEY_FIELDS = [Field("name", str, required=True), Field("secret", bool, default=True)]
CHECK_FIELDS = [Field("method", str, required=True), Field("path", str, required=True),
                Field("expect", list, default=[200], list_of=int)]


def _check_names(values: dict, where: str) -> list[str]:
    """Problems with account key names and hosts."""
    problems = [f"{where}: account key '{k}' must be CAPITAL_LETTERS_AND_UNDERSCORES"
                for k in values["account_keys"] if not KEY_NAME.match(k)]
    for host in values["hosts"]:
        if not HOST_NAME.match(host):
            problems.append(f"{where}: host '{host}' must be a bare domain name like example.com "
                            "(no scheme, port, path or *)")
    return problems


def _check_settings(values: dict, where: str, problems: list) -> list[dict]:
    """The checked [[account_settings]] rows (plain, non-secret settings kept with the account)."""
    rows = []
    for item in values["account_settings"]:
        row, bad = library.check_fields(item, SETTING_FIELDS, f"{where} account_settings")
        problems += bad
        if bad:
            continue
        if not SETTING_NAME.match(row["name"]):
            problems.append(f"{where}: account setting '{row['name']}' must be lower_case_with_underscores")
        if row["kind"] == "select" and not row["options"]:
            problems.append(f"{where}: account setting '{row['name']}' is a select but lists no options")
        rows.append(row)
    return rows


def _check_proxy(values: dict, where: str) -> list[str]:
    """Problems with the [proxy] and [check] blocks (needed for store-and-wire, forbidden for keys-only)."""
    proxy_block, check = values["proxy"], values["check"]
    if values["support"] == "keys-only":
        return [f"{where}: a keys-only service must not have a [{b}] block"
                for b, v in (("proxy", proxy_block), ("check", check)) if v is not None]
    if proxy_block is None:
        return [f"{where}: a store-and-wire service needs a [proxy] block"]
    try:
        spec = proxy.spec_from_service({"name": values["name"], "proxy": proxy_block})
    except ValueError as err:
        return [f"{where}: {err}"]
    problems = []
    if proxy_block["key"] not in values["account_keys"]:
        problems.append(f"{where}: [proxy] key '{proxy_block['key']}' is not listed in account_keys")
    if check is None:
        return problems + [f"{where}: a store-and-wire service needs a [check] block"]
    got, bad = library.check_fields(check, CHECK_FIELDS, f"{where} [check]")
    if not bad and proxy.find_rule(spec.rules, got["method"], got["path"]) is None:
        bad = [f"{where}: the [check] call {got['method']} {got['path']} is not one of the allowed calls"]
    return problems + bad


def _parse(data: dict, folder, where: str):
    """Check one service.toml; returns (service dict or None, problems)."""
    values, problems = library.check_fields(data, FIELDS, where)
    if values["name"] != folder.name:
        problems.append(f"{where}: name '{values['name']}' must match the folder name '{folder.name}'")
    keys = []
    if not problems:
        for item in values["project_keys"]:
            key, bad = library.check_fields(item, KEY_FIELDS, f"{where} project_keys")
            problems += bad
            keys.append(key)
        problems += _check_names(values, where) + _check_proxy(values, where)
        values["account_settings"] = _check_settings(values, where, problems)
    values["project_keys"] = keys
    values["secrets_file"] = values["secrets_file"] or f"service-{values['name']}.env"
    return (None if problems else values), problems


def load_library() -> dict:
    """Every service by name; a broken service.toml is left out (see load_problems)."""
    return {s["name"]: s for s in library.load_folders(paths.library() / "services", "service.toml", _parse)[0]}


def names_in(root) -> set[str]:
    """Names of the valid services in a library folder (root/services)."""
    found = library.load_folders(Path(root) / "services", "service.toml", _parse)[0]
    return {s["name"] for s in found}


def load_problems() -> list[str]:
    """Plain-words problems found in the services folder."""
    return library.load_folders(paths.library() / "services", "service.toml", _parse)[1]


def get(name: str) -> dict | None:
    """One service, or None when the library has none by that name."""
    return load_library().get(name)


# ---------- registry: HOME/config/services.toml (which account services are connected; never values) ----------
def registry_path():
    """HOME/config/services.toml."""
    return paths.config() / "services.toml"


def read_registry() -> dict:
    """The registry as {service name: table}; empty when there is no file or it is unreadable."""
    try:
        return tomllib.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def write_registry(data: dict) -> None:
    """Write the registry (names, times and check results only)."""
    atomic.write_text(registry_path(), tomlw.dumps(data, header="connected services; names only, never keys"))
