"""After an install: refresh the agent folder's knowledge pack and rules file, and grow Phoenix's own safety list."""
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, events, paths, settings

LOCAL_MARK = "## Server jobs"
RULES_NAME = "CLAUDE.md"
PACK_NAME = "phoenix-agent"
VERSION_FILE = "commands.md"
PENDING = "agent-rules-pending"


def agent_folder() -> Path:
    """The agent's folder (the `agent.folder` setting)."""
    return Path(settings.agent_settings()["folder"])


def installed_agent_dir() -> Path:
    """The installed copy's deploy/agent folder."""
    return paths.install() / "deploy" / "agent"


def _read(host, path: Path) -> str | None:
    """Text of a file (through the host adapter first, then the real disk); None when unreadable."""
    for reader in ((host.read_text,) if host is not None else ()) + (lambda p: Path(p).read_text(encoding="utf-8"),):
        try:
            return reader(path)
        except (OSError, UnicodeError):
            continue
    return None


def local_section(text: str) -> str:
    """Everything from the `## Server jobs` line to the end (kept byte for byte); empty when there is none."""
    match = re.search(rf"^{re.escape(LOCAL_MARK)}[^\n]*", text, re.M)
    return text[match.start():] if match else ""


def wanted_rules(host=None) -> str | None:
    """What the agent's rules file should be: the installed rules plus the folder's kept local section."""
    rules = _read(None, installed_agent_dir() / "agent-rules.md")
    if rules is None:
        return None
    current = _read(host, agent_folder() / RULES_NAME) or ""
    local = local_section(current)
    if not local:
        return rules
    return rules.rstrip("\n") + "\n\n" + local


def rules_current(host=None) -> tuple[bool, str]:
    """Whether the agent's rules file equals the installed rules plus its local section."""
    want = wanted_rules(host)
    if want is None:
        return True, "the installed copy ships no agent rules, so there is nothing to compare"
    have = _read(host, agent_folder() / RULES_NAME)
    if have is None:
        return False, f"{agent_folder() / RULES_NAME} cannot be read"
    return have == want, "agent rules current" if have == want else "agent rules out of date (older than the installed ones)"


def version_line(text: str | None) -> str:
    """The first line of a generated file (its `<!-- phoenix ... -->` version line)."""
    return (text or "").split("\n", 1)[0].strip()


def pack_current(host=None) -> tuple[bool, str]:
    """Whether the agent folder's knowledge pack carries the installed pack's version line."""
    src = installed_agent_dir() / "skills" / PACK_NAME
    want = version_line(_read(None, src / VERSION_FILE))
    if not want:
        return True, "the installed copy ships no knowledge pack, so there is nothing to compare"
    have = version_line(_read(host, agent_folder() / ".claude" / "skills" / PACK_NAME / VERSION_FILE))
    return have == want, "agent knowledge pack current" if have == want else "agent knowledge pack out of date (missing or older)"


def copy_skills() -> list[str]:
    """Copy deploy/agent/skills/ into the agent folder's .claude/skills/; returns the files written."""
    src = installed_agent_dir() / "skills"
    dst = agent_folder() / ".claude" / "skills"
    done = []
    if not src.is_dir():
        return done
    for f in sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = f.relative_to(src)
        atomic.write_text(dst / rel, f.read_text(encoding="utf-8"), 0o644)
        done.append(str(rel))
    return done


def refresh_rules() -> str:
    """Rebuild the agent's rules file; returns "same", "updated" or "missing" (nothing installed to copy)."""
    want = wanted_rules()
    if want is None:
        return "missing"
    target = agent_folder() / RULES_NAME
    try:
        have = target.read_text(encoding="utf-8")
    except OSError:
        have = None
    if have == want:
        return "same"
    if have is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        atomic.write_text(agent_folder() / ".phoenix" / "backups" / f"{RULES_NAME}.{stamp}", have, 0o600)
    atomic.write_text(target, want, 0o644)
    return "updated"


def refresh_agent(adapters) -> dict:
    """Copy the knowledge pack, rebuild the rules and restart the agent only if it is idle;
    {skills, rules, restarted}."""
    from phoenix9 import agentlink, chat
    files = copy_skills()
    result = refresh_rules()
    restarted = False
    if result == "updated":
        if agentlink.status(host=adapters.host)["state"] == "idle":
            chat.agent_restart(adapters, "its rules were updated")
            restarted = True
        else:
            atomic.write_text(paths.home() / PENDING, "agent rules updated; restart when idle\n", 0o644)
    return {"skills": len(files), "rules": result, "restarted": restarted}


def pending_restart() -> bool:
    """True while an updated rules file waits for an idle agent to restart."""
    return (paths.home() / PENDING).exists()


def clear_pending() -> None:
    """Forget the pending-restart note."""
    (paths.home() / PENDING).unlink(missing_ok=True)


def _toml(path: Path) -> dict:
    """A TOML file as a dict ({} when missing or unreadable)."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def add_safety_files() -> list[str]:
    """Add the installed self-project.toml's safety_files that Phoenix's live phoenix.toml lacks (never remove)."""
    wanted = _toml(paths.install() / "deploy" / "self-project.toml").get("safety_files") or []
    live = paths.projects() / "phoenix9" / "phoenix.toml"
    try:
        text = live.read_text(encoding="utf-8")
    except OSError:
        return []
    have = _toml(live).get("safety_files")
    have = have if isinstance(have, list) else []
    added = [w for w in wanted if isinstance(w, str) and w not in have]
    if not added:
        return []
    lines = "".join(f'  "{w}",\n' for w in added)
    match = re.search(r"^safety_files\s*=\s*\[(?:[^\]\"]|\"[^\"]*\")*?\]", text, re.M)
    if match:
        close = match.end() - 1
        new = text[:close].rstrip(" \t") + ("" if text[:close].endswith("\n") else "\n") + lines + text[close:]
    else:
        new = text.rstrip("\n") + "\nsafety_files = [\n" + lines + "]\n"
    atomic.write_text(live, new, 0o644)
    events.emit("update.safety_files_added", project=None, added=added)
    return added
