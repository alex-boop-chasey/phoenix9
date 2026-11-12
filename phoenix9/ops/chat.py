"""Ops for project chats: open a project's chat; shared by the CLI and the API."""
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
    """Put the project's chat to sleep; returns {state, changed, message}."""
    return _run(project, who, "sleep", lambda p, a: projectchat.sleep(p, a, who))


def off_chat(project: str, who: str = "cli") -> dict:
    """Turn the project's chat off; returns {state, changed, message}."""
    return _run(project, who, "off", lambda p, a: projectchat.off(p, a, who))

