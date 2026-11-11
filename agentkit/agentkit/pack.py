"""Site pack interface: the typed declarations a site supplies, and the loader that checks them."""
import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Risk = Literal["read", "change", "destructive"]
RISKS = ("read", "change", "destructive")


class PackError(Exception):
    """Raised when a site pack's declarations are not valid."""


@dataclass(frozen=True)
class ServerTool:
    """A tool that runs on the agent service; `inputs` is a Pydantic model."""

    name: str
    description: str
    inputs: type[BaseModel]
    risk: Risk
    function: Callable[..., Any]
    confirm_field: str | None = None  # the input whose value Alex must type to approve (destructive tools)
    one_per: str | None = None  # the input naming what the tool acts on; only one such call per value at a time


@dataclass(frozen=True)
class BrowserTool:
    """A tool the browser carries out; `inputs` is a Pydantic model."""

    name: str
    description: str
    inputs: type[BaseModel]
    result_fields: dict[str, tuple] | None = None  # allowed result keys, each with its allowed values; None keeps all


@dataclass(frozen=True)
class Pack:
    """Everything one site adds: instructions, tools, cards (tool name to React component) and settings."""

    name: str
    instructions: str
    server_tools: tuple[ServerTool, ...] = ()
    browser_tools: tuple[BrowserTool, ...] = ()
    components: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


def check_pack(pack: Pack) -> Pack:
    """Check a pack's declarations and return it, or raise PackError saying what is wrong."""
    names = [t.name for t in pack.server_tools] + [t.name for t in pack.browser_tools]
    for name in sorted({n for n in names if names.count(n) > 1}):
        raise PackError(f"Pack '{pack.name}': the tool name '{name}' is used more than once.")
    for tool in pack.server_tools:
        if tool.risk not in RISKS:
            raise PackError(f"Pack '{pack.name}': tool '{tool.name}' has unknown risk '{tool.risk}'.")
        if tool.risk == "destructive" and not tool.confirm_field:
            raise PackError(f"Pack '{pack.name}': destructive tool '{tool.name}' needs a confirm_field.")
        if tool.confirm_field and tool.confirm_field not in tool.inputs.model_fields:
            raise PackError(
                f"Pack '{pack.name}': tool '{tool.name}' confirms with '{tool.confirm_field}', which is not one of its inputs.")
    for tool_name, component in pack.components.items():
        if tool_name not in names:
            raise PackError(f"Pack '{pack.name}': a card is named for '{tool_name}', which is not a tool.")
        if not isinstance(component, str) or not component:
            raise PackError(f"Pack '{pack.name}': the card for '{tool_name}' has no component name.")
    return pack


def load_pack(name: str) -> Pack:
    """Import `agentkit.packs.<name>`, take its PACK, and check it."""
    try:
        module = importlib.import_module(f"agentkit.packs.{name}")
    except ModuleNotFoundError as err:
        if err.name and f"agentkit.packs.{name}".startswith(err.name):
            raise PackError(f"There is no site pack called '{name}'.") from err
        raise
    pack = getattr(module, "PACK", None)
    if not isinstance(pack, Pack):
        raise PackError(f"Pack '{name}' does not define PACK.")
    return check_pack(pack)
