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


def symlinked_part(path: Path) -> Path | None:
    """The first part of `path`, from inside the agent folder down to `path` itself, that is a symlink (None when none is)."""
    root = agent_folder()
    try:
        rel = Path(path).relative_to(root)
    except ValueError:
        return Path(path)       # outside the agent folder: never written
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            return cur
    return None


def _safe_target(path: Path) -> bool:
    """True when `path` can be written: no part of it inside the agent folder is a symlink; otherwise logged and False."""
    bad = symlinked_part(path)
    if bad is None:
        return True
    events.emit("agent.sync_skipped", project=None, path=str(path), symlink=str(bad),
                why="a folder or file on the way is a symlink, so nothing was written there")
    return False


def copy_skills() -> list[str]:
    """Copy deploy/agent/skills/ into the agent folder's .claude/skills/; returns the files written.
    A target with a symlink anywhere on its path inside the agent folder is skipped (and logged)."""
    src = installed_agent_dir() / "skills"
    dst = agent_folder() / ".claude" / "skills"
    done = []
    if not src.is_dir():
        return done
    for f in sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = f.relative_to(src)
        if not _safe_target(dst / rel):
            continue
        atomic.write_text(dst / rel, f.read_text(encoding="utf-8"), 0o644)
        done.append(str(rel))
    return done


def refresh_rules() -> str:
    """Rebuild the agent's rules file; returns "same", "updated", "missing" (nothing installed to copy) or
    "skipped" (a symlink on the way to the rules file or its backup: nothing written, logged)."""
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = agent_folder() / ".phoenix" / "backups" / f"{RULES_NAME}.{stamp}"
    if not _safe_target(target) or (have is not None and not _safe_target(backup)):
        return "skipped"
    if have is not None:
        atomic.write_text(backup, have, 0o600)
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


def _skip_safety(live: Path, why: str) -> list[str]:
    """Log that the safety list was left alone, and add nothing."""
    events.emit("update.safety_files_skipped", project=None, path=str(live), why=why)
    return []


def add_safety_files() -> list[str]:
    """Add the installed self-project.toml's safety_files that Phoenix's live phoenix.toml lacks (never remove).

    The live file is read with tomllib, the list grown (add only) and the file written back by the same writer
    `phoenix settings add` uses (same layout, atomic). A live file that does not parse is left alone (logged);
    the new text is parsed again before writing and nothing is written unless it gives back exactly the merged
    settings."""
    wanted = _toml(paths.install() / "deploy" / "self-project.toml").get("safety_files") or []
    folder = paths.projects() / "phoenix9"
    live = settings.project_file(folder)
    if not live.is_file():
        return []
    try:
        data = settings.load_project(folder)
    except settings.SettingsError as e:
        return _skip_safety(live, f"phoenix.toml does not parse, so it was left alone ({e})")
    have = data.get("safety_files")
    if have is not None and not isinstance(have, list):
        return _skip_safety(live, "safety_files in phoenix.toml is not a list, so it was left alone")
    have = list(have or [])
    added = []
    for w in wanted:
        if isinstance(w, str) and w not in have and w not in added:
            added.append(w)
    if not added:
        return []
    data["safety_files"] = have + added      # top level, never inside a table
    try:
        text = settings.render_project(data)
        again = tomllib.loads(text)
    except (TypeError, ValueError) as e:
        return _skip_safety(live, f"the new phoenix.toml would not parse ({e}), so nothing was written")
    if again != settings.prune(data):
        return _skip_safety(live, "the new phoenix.toml would not read back the same, so nothing was written")
    atomic.write_text(live, text)
    events.emit("update.safety_files_added", project=None, added=added)
    return added
