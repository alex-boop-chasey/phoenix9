"""Ops for project chats: state, open, sleep, forget and the status of all; shared by the CLI and the API."""
from phoenix9 import projectchat
from phoenix9.ops import common


def chat_state(project: str) -> dict:
    """The project's chat state {state, bridge_session_id, web_url, app_url, last_active}; the project must exist."""
    common.project_dir(project)
    try:
        return projectchat.state(project, common.make_adapters())
    except ValueError:
        raise common.NotFound("There is no project called '%s'." % project)


def open_chat(project: str, who: str = "cli") -> dict:
    """Open the project's chat and return {state, web_url, app_url, bridge_session_id, message}."""
    common.project_dir(project)
    try:
        data = projectchat.open_(project, common.make_adapters(), who)
    except ValueError:
        raise common.NotFound("There is no project called '%s'." % project)
    except projectchat.NotReady as err:
        common.record_command(who, "chat open %s" % project, project)
        raise common.Unavailable(str(err))
    common.record_command(who, "chat open %s" % project, project)
    return data


def _run(project: str, who: str, word: str, action) -> dict:
    """Run a chat action on a known project and record the command event."""
    common.project_dir(project)
    try:
        data = action(project, common.make_adapters())
    except ValueError:
        raise common.NotFound("There is no project called '%s'." % project)
    common.record_command(who, "chat %s %s" % (word, project), project)
    return data


def sleep_chat(project: str, who: str = "cli") -> dict:
    """Put the project's chat to sleep (wrap-up, then its unit stops); returns {state, changed, message}."""
    return _run(project, who, "sleep", lambda p, a: projectchat.sleep(p, a, who))


def forget_chat(project: str, who: str = "cli") -> dict:
    """Stop the project's chat and forget its saved conversation; returns {state, changed, message}."""
    return _run(project, who, "forget", lambda p, a: projectchat.forget(p, a, who))


def status_all() -> dict:
    """Every listed project's chat {name, state, last_active}, plus names of active chat units for unlisted ones."""
    from phoenix9 import chat, project as project_mod
    adapters = common.make_adapters()
    names = project_mod.project_names()
    rows = []
    for name in names:
        try:
            current = projectchat.state(name, adapters)
        except Exception:       # one unreadable chat must not hide the others
            current = {"state": "unknown", "last_active": None}
        rows.append({"name": name, "state": current["state"], "last_active": current.get("last_active")})
    unlisted = [n for n in chat.active_chat_names(adapters.host) if n not in names]
    return {"projects": rows, "unlisted": unlisted}
