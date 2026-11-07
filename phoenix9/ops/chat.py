"""Ops for project chats: open a project's chat; shared by the CLI and the API."""
from phoenix9 import projectchat
from phoenix9.ops import common


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
