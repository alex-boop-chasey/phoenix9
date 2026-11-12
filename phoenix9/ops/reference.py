"""Ops for a project's reference material: list, add and remove files and links in notes/reference."""
from phoenix9 import reference
from phoenix9.ops import common


def _guard(fn, *args, **kw):
    """Run a reference call, turning its refusals into the usual OpsError."""
    try:
        return fn(*args, **kw)
    except reference.ReferenceError_ as err:
        raise common.OpsError(str(err)) from None


def files(project: str) -> list:
    """The project's reference files, each with name, size, modified and kind."""
    common.project_dir(project)
    return _guard(reference.list_files, project)


def links(project: str) -> list:
    """The project's saved reference links, each with url and note."""
    common.project_dir(project)
    return _guard(reference.list_links, project)


def show(project: str) -> dict:
    """The project's reference files and links together."""
    return {"files": files(project), "links": links(project)}


def add(project: str, filename: str, data: bytes, who: str, replace: bool = False) -> dict:
    """Save one reference file in the project; returns its entry."""
    common.project_dir(project)
    entry = _guard(reference.add_file, project, filename, data, who, replace)
    common.record_command(who, f"reference add {project} {entry['name']}", project,
                          change=f"reference file {entry['name']} added")
    return entry


def remove(project: str, filename: str, who: str = "dashboard") -> dict:
    """Delete one reference file from the project."""
    common.project_dir(project)
    _guard(reference.remove_file, project, filename)
    common.record_command(who, f"reference remove {project} {filename}", project,
                          change=f"reference file {filename} removed")
    return {"project": project, "name": filename, "removed": True}


def add_links(project: str, text: str, who: str) -> dict:
    """Add the web links in some text to the project; returns what was added and the full list."""
    common.project_dir(project)
    result = _guard(reference.add_links, project, text, who)
    common.record_command(who, f"reference link {project}", project,
                          change=f"{len(result['added'])} reference link(s) added")
    return result


def remove_link(project: str, url: str, who: str = "dashboard") -> dict:
    """Remove one saved link from the project."""
    common.project_dir(project)
    _guard(reference.remove_link, project, url)
    common.record_command(who, f"reference unlink {project}", project, change="reference link removed")
    return {"project": project, "url": url, "removed": True}
