"""Ops for projects: list, show, edit, open, close, set-chat, new and the templates menu."""
from phoenix9.ops import common


def list_() -> list:
    """Every project (a folder with a CLAUDE.md) with its full info, by name."""
    from phoenix9 import project
    return project.list_projects(common.make_adapters())


list = list_


def show(name: str) -> dict:
    """All info of one project, plus recent changelog lines and open gates."""
    from phoenix9 import project
    common.project_dir(name)
    return project.show_project(name, common.make_adapters())


def edit(name: str, who: str, description=None, profile=None, repo=None) -> dict:
    """Change a project's description, profile or repo."""
    from phoenix9 import project
    common.project_dir(name)
    return project.edit(name, common.make_adapters(), who, description, profile, repo)


def open_(name: str, who: str) -> dict:
    """Switch a project's chat server on."""
    from phoenix9 import project
    common.project_dir(name)
    return project.open_project(name, common.make_adapters(), who)


def close(name: str, who: str, force: bool = False) -> dict:
    """Switch a project's chat server off."""
    from phoenix9 import project
    common.project_dir(name)
    return project.close_project(name, common.make_adapters(), who, force)


def set_chat(name: str, url: str, who: str) -> dict:
    """Save a project's chat session link."""
    from phoenix9 import project
    common.project_dir(name)
    return project.set_chat(name, url, who)


def new(opts: dict, who: str, progress=None) -> dict:
    """Create a project from the form; `progress` gets one plain line per creation step."""
    from phoenix9 import project
    return project.create(opts, common.make_adapters(), who, progress)


def templates_menu() -> list:
    """The templates a new project can start from."""
    from phoenix9 import templates
    return [{k: t[k] for k in ("name", "title", "profile", "kind", "check")} for t in templates.load_menu()]
