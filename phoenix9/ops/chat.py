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


SKIPPED_PROJECTS = ("phoenix9", "home")


def catch_up_todo() -> list:
    """Names of existing projects without a readable chat document (phoenix9 and home have their own chats)."""
    from phoenix9 import project
    return [n for n in project.project_names()
            if n not in SKIPPED_PROJECTS and projectchat.read_chat_doc(n)[0] is None]


def catch_up(who: str = "cli", go: bool = False, say=None) -> dict:
    """List (or, with go, set up one at a time) the chats still missing; returns {todo, results, failed}."""
    todo = catch_up_todo()
    results = []
    if go:
        adapters = common.make_adapters()
        for name in todo:
            data = projectchat.set_up(name, adapters, who)
            results.append({"project": name, "ok": data["chat"] == "sleeping", "chat": data["chat"],
                            "message": data.get("chat_message", "The chat is set up and sleeping.")})
            if say:
                say(results[-1])
    common.record_command(who, "chat catch-up" + (" --all" if go else ""))
    return {"all": go, "todo": todo, "results": results, "failed": sum(1 for r in results if not r["ok"])}
