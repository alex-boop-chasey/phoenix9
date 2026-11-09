"""Git for Phoenix 9: run worktrees, listing and checking a run's changes, secret scan, commits.

Ported from reference/v8/phoenix/git.py. Every git command gets the safe flags (hard rule 5).
Phoenix works on the project's local `code/` repo: each run gets a worktree on `phoenix/<run-id>`.
Nothing here pushes, adds remotes or talks to GitHub.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# ported from reference/v8/phoenix/git.py:35
SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")   # hard rule 5
SHA_RE = re.compile(r"[0-9a-f]{40}")
IDENT = ("-c", "user.name=Phoenix", "-c", "user.email=phoenix@localhost")
MAIN = "main"
BRANCH_PREFIX = "phoenix/"
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RESERVED_RUN_IDS = {"main", "master", "head"}
ENV_EXAMPLES = {".env.example", ".env.sample"}

# ported from reference/v8/phoenix/git.py:76 (AWS-style key added, matched on text not bytes)
SECRET_PATTERNS = [
    (re.compile(r"sk_live_"), "a live Stripe key (sk_live_)"),
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY"), "a private key (-----BEGIN ... PRIVATE KEY)"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "an AWS access key (AKIA...)"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "a GitHub token (ghp_/github_pat_)"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"), "an Anthropic key (sk-ant-)"),
]
MIN_SECRET_LEN = 8

# ported from reference/v8/phoenix/git.py:84
_STRIP = ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG",
          "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
          "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PROXY_COMMAND")

SYMLINK, SUBMODULE = "120000", "160000"


class GitError(Exception):
    """A git command failed. The message says which one and why."""


class Rejected(Exception):
    """The builder's work was refused. `reasons` lists each problem in plain English."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("The builder's changes were rejected: " + "; ".join(reasons))


@dataclass
class Change:
    """One changed path: status letter (A, M, D, T, R), path, new file mode, and extras."""

    status: str
    path: str
    mode: str = "100644"
    old_path: str = ""       # for renames: where the file came from
    old_mode: str = ""       # the mode before (spots chmod)
    binary: bool = False


# ------------------------------------------------------------- running git
def git_env() -> dict[str, str]:
    """Return the environment for git: no GIT_* overrides, no global or system config, no prompts."""
    env = {k: v for k, v in os.environ.items()
           if k not in _STRIP and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def git_argv(*args: str) -> list[str]:
    """Return the full command line for one git call, safe flags included."""
    return ["git", *SAFE, *args]


def run_git(cwd: Path, *args: str, check: bool = True, input: bytes | None = None,
            timeout: int = 600) -> subprocess.CompletedProcess:
    """Run one git command in `cwd` with the safety flags. Raise GitError on failure when `check`."""
    try:
        trust = ("-c", f"safe.directory={Path(cwd).resolve()}")  # worktrees are handed to the agent uid
        p = subprocess.run(["git", *SAFE, *trust, *args], cwd=str(cwd), capture_output=True, env=git_env(),
                           input=input, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)} in {cwd}: timed out after {timeout}s") from e
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} in {cwd}: {p.stderr.decode(errors='replace').strip()}")
    return p


def git(cwd: Path, *args: str, check: bool = True, input: bytes | None = None) -> str:
    """Run one git command and return its output as text."""
    return run_git(cwd, *args, check=check, input=input).stdout.decode(errors="replace")


def head(path: Path) -> str:
    """Return the commit sha checked out in a repo folder."""
    return git(path, "rev-parse", "HEAD").strip()


def rmtree(p: Path) -> None:
    """Delete a folder written by a container. Never follows symlinks."""
    # ported from reference/v8/phoenix/git.py:192
    if not p.exists() and not p.is_symlink():
        return

    def onexc(func, path, exc):
        parent = os.path.dirname(path)
        try:
            if not os.path.islink(parent):
                os.chmod(parent, 0o700)
            if not os.path.islink(path) and os.path.isdir(path):
                os.chmod(path, 0o700)
        except OSError:
            pass
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=onexc)
    else:
        shutil.rmtree(p, onerror=onexc)


# ------------------------------------------------------------- branches and worktrees
def branch_name(run_id: str) -> str:
    """Return `phoenix/<run-id>`, refusing anything that is not a plain run id."""
    if not RUN_ID_RE.fullmatch(run_id or "") or run_id.lower() in RESERVED_RUN_IDS:
        raise GitError(f"'{run_id}' is not a run id; Phoenix only uses branches named phoenix/<run-id>.")
    return BRANCH_PREFIX + run_id


def _branch_exists(code_dir: Path, name: str) -> bool:
    """True when the local branch exists."""
    return run_git(code_dir, "rev-parse", "-q", "--verify", f"refs/heads/{name}^{{commit}}",
                   check=False).returncode == 0


def default_branch(code_dir: Path) -> str:
    """Return `main` if the repo has it, else the branch the repo is on now."""
    if _branch_exists(code_dir, MAIN):
        return MAIN
    current = git(code_dir, "symbolic-ref", "-q", "--short", "HEAD", check=False).strip()
    if not current:
        raise GitError(f"{code_dir} has no '{MAIN}' branch and is not on a branch; make a first commit first.")
    return current


def make_worktree(code_dir: Path, run_id: str, work_dir: Path) -> Path:
    """Create the run's worktree at `work_dir` on branch `phoenix/<run-id>` (made from main). Return it.

    If the branch already exists (a restarted run) it is checked out as it is.
    """
    name = branch_name(run_id)
    code_dir, work_dir = Path(code_dir), Path(work_dir)
    if work_dir.exists() or work_dir.is_symlink():
        raise GitError(f"{work_dir} already exists; not making a worktree there.")
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    if _branch_exists(code_dir, name):
        git(code_dir, "worktree", "add", "-q", "--", str(work_dir), name)
    else:
        git(code_dir, "worktree", "add", "-q", "-b", name, "--", str(work_dir), default_branch(code_dir))
    return work_dir


def remove_worktree(code_dir: Path, work_dir: Path) -> None:
    """Delete the worktree folder and forget it. The branch stays."""
    code_dir, work_dir = Path(code_dir), Path(work_dir)
    rmtree(work_dir)
    git(code_dir, "worktree", "prune")


def fresh_checkout(worktree: Path, dest: Path) -> Path:
    """Make a clean detached checkout of the worktree's HEAD at `dest`, with its uncommitted changes applied."""
    worktree, dest = Path(worktree), Path(dest)
    patch = diff_text(worktree, "HEAD", binary=True)
    git(worktree, "worktree", "add", "-q", "--detach", "--", str(dest), "HEAD")
    if patch.strip():
        git(dest, "apply", "--whitespace=nowarn", input=patch.encode())
    return dest


def commit_checkout(repo: Path, sha: str, dest: Path) -> Path:
    """Make a clean detached checkout of exactly this commit at `dest` (nothing uncommitted comes with it)."""
    if not SHA_RE.fullmatch(sha or ""):
        raise GitError(f"not a full commit id: {sha!r}")
    git(Path(repo), "worktree", "add", "-q", "--detach", "--", str(Path(dest)), sha)
    return Path(dest)


def snapshot_clone(code_dir: Path, dest: Path) -> Path:
    """A standalone copy of the repo's default branch at `dest` (own .git, objects copied, no remote), so a
    container can be handed it without anything of the live code/ folder being mounted."""
    code_dir, dest = Path(code_dir), Path(dest)
    branch = default_branch(code_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "clone", "-q", "--no-hardlinks", "--single-branch", "--branch", branch, "--",
        str(code_dir.resolve()), str(dest))
    git(dest, "remote", "remove", "origin")
    return dest


def remove_checkout(worktree: Path, dest: Path) -> None:
    """Delete a checkout made by fresh_checkout and forget it."""
    rmtree(Path(dest))
    git(Path(worktree), "worktree", "prune")


# ------------------------------------------------------------- changes
def _stage_all(worktree: Path) -> None:
    """Stage everything in the worktree so new files show up in the diff."""
    git(worktree, "add", "-A")


def _binary_paths(worktree: Path, base: str) -> set[str]:
    """Return the paths git treats as binary in the diff against base."""
    out = git(worktree, "diff", "--cached", "--numstat", "-z", "-M", base)
    parts, i, found = out.split("\0"), 0, set()
    while i < len(parts) and parts[i]:
        added, _, rest = parts[i].partition("\t")
        deleted, _, path = rest.partition("\t")
        if path == "":                      # rename: "a\td\t\0old\0new\0"
            path, i = parts[i + 2], i + 3
        else:
            i += 1
        if added == "-" and deleted == "-":
            found.add(path)
    return found


def diff_changes(worktree: Path, base: str) -> list[Change]:
    """List every path the worktree changed against `base` (committed or not), with modes."""
    worktree = Path(worktree)
    _stage_all(worktree)
    out = git(worktree, "diff", "--cached", "--raw", "-z", "-M", base)
    binary = _binary_paths(worktree, base)
    parts, i, changes = out.split("\0"), 0, []
    while i < len(parts) and parts[i].startswith(":"):
        old_mode, new_mode, _, _, st = parts[i][1:].split(" ")
        if st[0] in "RC":
            old, new, i = parts[i + 1], parts[i + 2], i + 3
        else:
            old, new, i = "", parts[i + 1], i + 2
        changes.append(Change(status=st[0], path=new, mode=new_mode, old_path=old,
                              old_mode=old_mode, binary=new in binary))
    return changes


def diff_text(worktree: Path, base: str, binary: bool = False) -> str:
    """Return the full text diff of the worktree against `base` (binary=True: a patch that applies binary files too)."""
    _stage_all(Path(worktree))
    extra = ["--binary"] if binary else []
    return git(Path(worktree), "diff", "--cached", "-M", *extra, base)


def reset_attempt(worktree: Path, base: str) -> None:
    """Throw an attempt away: hard reset to `base` and delete untracked files."""
    git(worktree, "reset", "-q", "--hard", base)
    git(worktree, "clean", "-qffd")


def _clean_trailer(text: str) -> str:
    """Make a trailer key or value one plain line."""
    return " ".join(str(text).split())


def pending_paths(worktree: Path, skip_env: bool = False) -> list[str]:
    """Paths with uncommitted changes (new, changed or deleted); skip_env leaves out .env-style files."""
    out = git(Path(worktree), "status", "--porcelain", "-z", "--untracked-files=all")
    found, parts, i = [], out.split("\0"), 0
    while i < len(parts) and parts[i]:
        entry = parts[i]
        found.append(entry[3:])
        i += 2 if entry[0] in "RC" else 1        # a rename is followed by its old path
    return [p for p in found if not (skip_env and is_env_file(p.rsplit("/", 1)[-1]))]


def commit(worktree: Path, message: str, trailers: dict, skip_env: bool = False,
           allow_empty: bool = True, author: str = "") -> str:
    """Commit everything in the worktree with trailers (`Key: value`). Return the new sha.

    By default a commit with no changes is still made, so the step's pass is on record; allow_empty=False
    raises GitError("Nothing to commit") instead. skip_env=True leaves .env-style files out of the commit
    (they stay in the worktree, uncommitted). `author` is "Name <email>" (default: Phoenix).
    """
    lines = [ln for ln in message.strip().splitlines()]
    body = "\n".join(lines).strip() or "Phoenix step"
    keys = {_clean_trailer(k).lower() for k in trailers}
    body = "\n".join(ln for ln in body.splitlines()
                     if _clean_trailer(ln.partition(":")[0]).lower() not in keys)
    block = "\n".join(f"{_clean_trailer(k)}: {_clean_trailer(v)}" for k, v in trailers.items())
    _stage_all(Path(worktree))
    if skip_env:
        staged = git(Path(worktree), "diff", "--cached", "--name-only", "-z").split("\0")
        env = [p for p in staged if p and is_env_file(p.rsplit("/", 1)[-1])]
        if env:
            git(Path(worktree), "reset", "-q", "--", *env)
    if not allow_empty and run_git(Path(worktree), "diff", "--cached", "--quiet", check=False).returncode == 0:
        raise GitError("Nothing to commit")
    text = f"{body}\n\n{block}\n" if block else f"{body}\n"
    ident = IDENT
    if author:
        name, _, email = author.partition("<")
        ident = ("-c", f"user.name={name.strip()}", "-c", f"user.email={email.rstrip('> ').strip()}")
    flags = ["--allow-empty"] if allow_empty else []
    git(worktree, *ident, "commit", "-q", *flags, "--no-verify", "-F", "-", input=text.encode())
    return head(worktree)


FIX_BY_CHAT = re.compile(r"^Phoenix-Fix-By:\s*chat:", re.I | re.M)


def has_chat_fix(code_dir: Path, base: str, tip: str) -> bool:
    """True when any commit in base..tip carries a `Phoenix-Fix-By: chat:...` trailer (a fix by the Phoenix
    agent or a project chat). Raises GitError when git cannot tell."""
    return bool(FIX_BY_CHAT.search(git(Path(code_dir), "log", "--format=%B%x00", f"{base}..{tip}")))


def passed_tasks(worktree: Path, base_sha: str) -> list[int]:
    """Return the task numbers that have a Phoenix-Task trailer in `git log base..HEAD`, sorted."""
    # ported from reference/v8/phoenix/git.py:679
    if not re.fullmatch(r"[0-9a-f]{7,64}", base_sha or ""):
        raise GitError(f"'{base_sha}' is not a commit sha")
    out = git(Path(worktree), "log", "--format=%(trailers:key=Phoenix-Task,valueonly,separator=%x2C)%x1e",
              f"{base_sha}..HEAD")
    tasks: set[int] = set()
    for record in out.split("\x1e"):
        for value in record.strip().split(","):
            if value.strip().isdigit():
                tasks.add(int(value.strip()))
    return sorted(tasks)


# ------------------------------------------------------------- allow / deny
def is_env_file(basename: str) -> bool:
    """True for .env, .env.<anything> and .dev.vars (but not .env.example / .env.sample)."""
    b = basename.lower()
    return (b == ".env" or b.startswith(".env.") or b == ".dev.vars") and b not in ENV_EXAMPLES


def _gitlike(seg: str) -> bool:
    """True for names git may treat as its own folder (.git, git~1, .git::...)."""
    s = seg.lower().rstrip(". ")
    return s in (".git", "git~1") or s.startswith(".git::")


def _locked(path: str, locked) -> bool:
    """True when the path is locked (an exact file, or anything under a folder ending in /)."""
    p = path.lower()
    for item in locked:
        s = str(item).lower().lstrip("/")
        if (s.endswith("/") and p.startswith(s)) or p == s:
            return True
    return False


def _matches(path: str, patterns) -> bool:
    """True when the path matches any fnmatch pattern (also by file name alone)."""
    base = path.split("/")[-1]
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(base, p) for p in patterns)


def _never_allowed(path: str, c: Change) -> str:
    """Return why a path can never be allowed (.git, symlinks, submodules), or ""."""
    if SYMLINK in (c.mode, c.old_mode) and c.status != "D" or c.mode == SUBMODULE:
        return "symlinks and submodules are not allowed"
    if any(_gitlike(s) for s in path.split("/")):
        return "'.git' belongs to Phoenix"
    return ""


def _default_deny(path: str, c: Change) -> str:
    """Return why the default deny list refuses a path, or ""."""
    segs = path.split("/")
    lsegs = [s.lower() for s in segs]
    base = lsegs[-1]
    if c.status != "D" and is_env_file(segs[-1]):
        return "environment files are never committed (the values live in the project's keys)"
    if ".github" in lsegs and "workflows" in lsegs[lsegs.index(".github") + 1:]:
        return ".github/workflows is automation Phoenix and the owner control"
    if ".claude" in lsegs:
        return ".claude/ is the agent's own settings, which the owner controls"
    if base in ("claude.md", ".mcp.json"):
        return f"{segs[-1]} belongs to the owner (agent instruction or config file)"
    return ""


def check_changes(changes: list[Change], *, deny_extra=(), allow_extra=(), locked=()) -> list[str]:
    """Return a plain reason for every change that is not allowed (empty list means all fine).

    Default deny: .git, .github/workflows, .env* (not .env.example/.env.sample), symlinks,
    submodules, CLAUDE.md, .claude/, .mcp.json, and the `locked` paths. `allow_extra` patterns
    override the default deny, except for .git, symlinks, submodules and locked paths.
    `deny_extra` patterns add to it. A rename is checked at both ends.
    """
    bad = []
    for c in changes:
        why = ""
        for path in filter(None, (c.path, c.old_path)):
            why = _never_allowed(path, c) or _locked_reason(path, locked)
            if not why:
                d = _default_deny(path, c)
                if d and not _matches(path, allow_extra):
                    why = d
            if not why and _matches(path, deny_extra):
                why = "this project does not allow changes here"
            if why:
                break
        if why:
            where = f"{c.old_path} -> {c.path}" if c.old_path else c.path
            bad.append(f"{c.status} {where}: {why}")
    return bad


def _locked_reason(path: str, locked) -> str:
    """Return the reason for a locked path, or ""."""
    return "this file holds the step's locked checks" if _locked(path, locked) else ""


# ------------------------------------------------------------- secrets
def scan_secrets(diff_text: str) -> list[str]:
    """Return what looks like a secret among the lines a diff adds (descriptions only, never values).

    Files named .env.example / .env.sample are skipped: they hold placeholders.
    """
    found: list[str] = []
    path, skip = "", False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/.* b/(.*)$", line)
            path = m.group(1) if m else ""
            skip = path.split("/")[-1].lower() in ENV_EXAMPLES
            continue
        if skip or not line.startswith("+") or line.startswith("+++"):
            continue
        for pattern, what in SECRET_PATTERNS:
            if pattern.search(line):
                msg = f"{path}: contains {what}"
                if msg not in found:
                    found.append(msg)
    return found


# ported from reference/v8/phoenix/git.py:603
def secret_forms(values) -> dict[str, str]:
    """Map every written form of each secret value (raw, JSON-escaped, url-encoded, base64) to a label.

    Values under 8 characters are skipped (they match ordinary words). Labels never hold the value.
    """
    forms: dict[str, str] = {}
    for n, value in enumerate(dict.fromkeys(v for v in values if isinstance(v, str)), 1):
        if len(value) < MIN_SECRET_LEN:
            continue
        raw = value.encode("utf-8")
        b64 = base64.b64encode
        for f in (value, json.dumps(value)[1:-1], quote(value, safe=""), b64(raw).decode().rstrip("="),
                  b64(b" " + raw).decode()[2:].rstrip("="), b64(b"  " + raw).decode()[3:].rstrip("=")):
            if len(f) >= MIN_SECRET_LEN:
                forms.setdefault(f, "a known secret value")
    return forms


# ported from reference/v8/phoenix/git.py:625
def find_secrets(text: str, forms: dict[str, str]) -> list[str]:
    """Return plain descriptions of the secrets found in some text (what kind, never the value)."""
    out = sorted({what for form, what in forms.items() if form in text})
    return out + [what for pattern, what in SECRET_PATTERNS if pattern.search(text) and what not in out]


def scan_added_lines(diff_text: str, forms: dict[str, str]) -> list[tuple[str, int, str]]:
    """Return (file, line number, what) for each added diff line holding a secret; never the value."""
    found: list[tuple[str, int, str]] = []
    path, skip, line_no = "", False, 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/.* b/(.*)$", line)
            path = m.group(1) if m else ""
            skip, line_no = path.split("/")[-1].lower() in ENV_EXAMPLES, 0
        elif line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            line_no = int(m.group(1)) if m else 0
        elif line.startswith("+++") and not line_no:
            continue
        elif line.startswith("+"):
            if not skip:
                for what in find_secrets(line[1:], forms):
                    found.append((path, line_no, what))
            line_no += 1
        elif line.startswith(" "):
            line_no += 1
    return found


def remote_url(code_dir: Path) -> str:
    """The URL of the `origin` remote of a repo, or '' when there is none."""
    try:
        done = subprocess.run(["git", *SAFE, "-C", str(code_dir), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""
