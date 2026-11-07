"""Card plug-ins: one module per card type, loaded by type name, with a check of the query against its schema."""
import importlib
import pkgutil
import re

_TYPE = re.compile(r"[a-z][a-z-]{0,39}")
_CHECKS = {"str": lambda v: isinstance(v, str),
           "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
           "bool": lambda v: isinstance(v, bool),
           "list[str]": lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
           "dict": lambda v: isinstance(v, dict),
           "list": lambda v: isinstance(v, list)}


def types() -> list[str]:
    """The card types that exist, sorted, written with '-' (settings-preview)."""
    found = [m.name.replace("_", "-") for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_")]
    return sorted(found)


def load(card_type: str):
    """The module for a card type, or None when there is no such type."""
    if not isinstance(card_type, str) or not _TYPE.fullmatch(card_type) or card_type not in types():
        return None
    return importlib.import_module(f"{__name__}.{card_type.replace('-', '_')}")


def check_query(module, query) -> str | None:
    """Plain reason the query does not fit the module's schema, or None when it fits."""
    if not isinstance(query, dict):
        return "The query must be an object."
    schema = module.schema
    for key, value in query.items():
        if key not in schema:
            return f"'{key}' is not a query key of this card. Allowed: {', '.join(sorted(schema)) or 'none'}."
        if not _CHECKS[schema[key]](value):
            return f"'{key}' must be of type {schema[key]}."
    return None
