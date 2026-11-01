"""Phoenix's own git clone of a project, the run branch, and bringing the builder's work back.

Phoenix keeps one clone per project at `cache/repos/<repo-name>/`. It is the
only `.git` Phoenix trusts (hard rule 3). The builder never touches it: the
builder gets a fresh copy (a "workspace") for each try, and afterwards
Phoenix copies the plain files back (`snapshot`), checks every changed path,
scans for secrets, and only then commits. A commit carries `Phoenix-Run` and
`Phoenix-Step` trailers; those trailers are the record of which steps passed.

Every git command gets `-c core.fsmonitor=false -c core.hooksPath=/dev/null`
(hard rule 5). Network commands log in to GitHub over HTTPS with a credential
helper script that reads GH_TOKEN from `config/github.env` when git asks; the
token never goes into a URL, a config file or a workspace. Phoenix only ever
pushes `phoenix/<run-id>` branches (hard rule 6).
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets as _random
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from phoenix import config
from phoenix.claude import MIN_SECRET_LEN, read_env_file

SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")   # hard rule 5
IDENT = ("-c", "user.name=Phoenix", "-c", "user.email=phoenix@localhost")
MAIN = "main"
BRANCH_PREFIX = "phoenix/"
CREDENTIAL_SCRIPT = Path(__file__).resolve().parent / "git-credential.sh"
GITHUB_BASE = "https://github.com"
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RESERVED_RUN_IDS = {"main", "master", "head"}           # never a branch Phoenix may own
TRAILER_RUN = "Phoenix-Run"
TRAILER_STEP = "Phoenix-Step"
LOCK_MANIFEST = "tests/phoenix/manifest.json"          # the check lock (phoenix/checks.py)

# Folders the snapshot never copies back: git's own folder, installed packages,
# and the test tools' output (Playwright: test-results, playwright-report,
# blob-report, playwright/.cache; Vitest: coverage, .vitest).
SKIP_DIRS = {".git", "node_modules", "test-results", "playwright-report", "blob-report", "coverage", ".vitest"}
SKIP_PATHS = {"playwright/.cache"}

# Borrowed from Phoenix 0.6.0 hands/workspace.py:21-44 (DENY_TOP and DENY_EXT left out;
# `.phoenix` added: it holds Phoenix's own run files such as the plan).
# Always rejected. The builder may never write instructions for itself or anyone
# else, or change CI.
DENY_SEGMENTS = {".claude", ".github", ".git", ".husky", ".cursor", ".vscode", ".devcontainer", ".phoenix"}
DENY_BASENAMES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".mcp.json", ".cursorrules",
                  ".gitmodules", ".gitattributes", "claude.json", ".clauderc"}
# all comparisons are case-insensitive (macOS/Windows clones fold case)
DENY_SEGMENTS_CI = {x.lower() for x in DENY_SEGMENTS}
DENY_BASENAMES_CI = {x.lower() for x in DENY_BASENAMES}
# Test-tool settings the builder could use to switch checks off.
DENY_CONFIG_PREFIXES = ("vitest.config.", "playwright.config.")
# Next.js 16 writes a root AGENTS.md made only of these marked blocks whenever
# `next dev` runs under an AI agent (it sees CLAUDECODE=1). It is the tool's
# file, not the builder's: a NEW one of exactly this shape is left out of the
# snapshot instead of refusing the whole try. Anything else in it is refused.
TOOL_AGENTS_MD = re.compile(
    r"\s*(?:<!-- BEGIN:nextjs-agent-(rules|feedback) -->.*?<!-- END:nextjs-agent-\1 -->\s*)+",
    re.DOTALL)
# Environment files never enter the repo; only the names-only templates may.
ENV_EXAMPLES = {".env.example", ".env.sample"}

# Patterns that are never allowed in a commit, whatever the env file says.
SECRET_PATTERNS = [
    (re.compile(rb"sk_live_"), "a live Stripe key (sk_live_)"),
    (re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY"), "a private key (-----BEGIN ... PRIVATE KEY)"),
]

# Git must use only each repo's own config: env overrides and global/system
# config (url.insteadOf, credential helpers) could change where git talks to.
# Borrowed from Phoenix 0.6.0 hands/gitops.py:11-17.
_STRIP = ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG",
          "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
          "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PROXY_COMMAND")


class GitError(Exception):
    """A git command failed. The message says which one and why."""


class Rejected(Exception):
    """The builder's work was refused. `reasons` lists each problem in plain English."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("The builder's changes were rejected: " + "; ".join(reasons))


@dataclass
class Change:
    """One changed path in a snapshot: status letter (A, M, D, T), path, and the new file mode."""

    status: str
    path: str
    mode: str = "100644"


# ------------------------------------------------------------- running git
def git_env() -> dict[str, str]:
    """Return the environment for git: no GIT_* overrides, no global or system config, no prompts."""
    env = {k: v for k, v in os.environ.items()
           if k not in _STRIP and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def run_git(cwd: Path, *args: str, check: bool = True, input: bytes | None = None,
            timeout: int = 600) -> subprocess.CompletedProcess:
    """Run one git command in `cwd` with the safety flags. Raise GitError on failure when `check`."""
    argv = ["git", *SAFE, *args]
    try:
        p = subprocess.run(argv, cwd=str(cwd), capture_output=True, env=git_env(), input=input, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)} in {cwd}: timed out after {timeout}s") from e
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} in {cwd}: {p.stderr.decode(errors='replace').strip()}")
    return p


def git(cwd: Path, *args: str, check: bool = True, input: bytes | None = None) -> str:
    """Run one git command and return its output as text."""
    return run_git(cwd, *args, check=check, input=input).stdout.decode(errors="replace")


def auth_flags() -> list[str]:
    """Return the -c flags that make git ask the credential helper script for GH_TOKEN."""
    env_file = config.paths().config / "github.env"
    helper = f"!sh {shlex.quote(str(CREDENTIAL_SCRIPT))} {shlex.quote(str(env_file))}"
    return ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]


def net_git(cwd: Path, *args: str, check: bool = True) -> str:
    """Run a git command that talks to origin (clone, fetch, ls-remote, push), with the login helper."""
    return run_git(cwd, *auth_flags(), *args, check=check, timeout=900).stdout.decode(errors="replace")


# ------------------------------------------------------------- names and places
def repo_name(repo: str) -> str:
    """Return the name part of `owner/name` (the clone's folder name)."""
    name = repo.split("/")[-1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
        raise GitError(f"'{repo}' is not a repo name like owner/name.")
    return name


def origin_url(repo: str) -> str:
    """Return the HTTPS address of the project on GitHub (no token in it).

    PHOENIX_GIT_BASE replaces https://github.com (tests point it at a folder of bare repos).
    """
    base = os.environ.get("PHOENIX_GIT_BASE") or GITHUB_BASE
    if base == GITHUB_BASE:
        return f"{base}/{repo}.git"
    return f"{base.rstrip('/')}/{repo_name(repo)}.git"


def clone_dir(repo: str) -> Path:
    """Return Phoenix's own clone of the project: cache/repos/<repo-name>/."""
    return config.paths().cache / "repos" / repo_name(repo)


def work_root() -> Path:
    """Return the folder that holds workspaces and check checkouts: cache/work/."""
    return config.paths().cache / "work"


def branch_name(run_id: str) -> str:
    """Return `phoenix/<run-id>`, refusing anything that is not a plain run id."""
    if not RUN_ID_RE.fullmatch(run_id or "") or run_id.lower() in RESERVED_RUN_IDS:
        raise GitError(f"'{run_id}' is not a run id; Phoenix only uses branches named phoenix/<run-id>.")
    return BRANCH_PREFIX + run_id


def head(path: Path) -> str:
    """Return the commit sha checked out in a repo folder."""
    return git(path, "rev-parse", "HEAD").strip()


def rmtree(p: Path) -> None:
    """Delete a folder written by a container. Never follows symlinks.

    Borrowed from Phoenix 0.6.0 hands/workspace.py:50-70.
    """
    if not p.exists() and not p.is_symlink():
        return

    def onexc(func, path, exc):
        # dirs written read-only by the agent: make the parent writable and retry (never chmod via a symlink)
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


def clean(path: Path) -> None:
    """Throw away everything in Phoenix's clone that is not committed."""
    git(path, "reset", "-q", "--hard", "HEAD")
    git(path, "clean", "-qfdx")


# ------------------------------------------------------------- 1. clone and run branch
def ensure_clone(repo: str) -> Path:
    """Make sure Phoenix's own clone exists and has the latest origin/main. Return its folder."""
    d = clone_dir(repo)
    url = origin_url(repo)
    if not (d / ".git").is_dir():
        rmtree(d)
        d.parent.mkdir(parents=True, exist_ok=True)
        net_git(d.parent, "clone", "-q", "--no-hardlinks", "--template=", "--", url, d.name)
    else:
        git(d, "remote", "set-url", "origin", url)
        net_git(d, "fetch", "-q", "--prune", "origin")
    if not git(d, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{MAIN}^{{commit}}", check=False).strip():
        raise GitError(f"{repo} has no '{MAIN}' branch on GitHub. Phoenix builds on top of main; "
                       "push at least one commit to main first.")
    return d


def remote_sha(path: Path, ref: str) -> str:
    """Return the sha of `ref` (refs/heads/x) on origin, or "" when origin does not have it."""
    out = net_git(path, "ls-remote", "origin", ref)
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == ref:
            return sha.strip()
    return ""


def start_branch(repo: str, run_id: str) -> str:
    """Check out `phoenix/<run-id>` in Phoenix's clone, creating it from origin/main. Return the base sha.

    Safe to call again (after a crash or restart): an existing local branch is
    kept as it is; failing that, the branch on GitHub is used; only when
    neither exists is a new branch made from origin/main. The base sha is
    where the run branch left main, so it stays the same on every call.
    Borrowed from Phoenix 0.6.0 hands/loop.py:412-439 (open_round), without the tags.
    """
    name = branch_name(run_id)
    d = ensure_clone(repo)
    clean(d)
    main_sha = git(d, "rev-parse", f"refs/remotes/origin/{MAIN}").strip()
    local = git(d, "rev-parse", "-q", "--verify", f"refs/heads/{name}^{{commit}}", check=False).strip()
    if local:
        if git(d, "symbolic-ref", "-q", "HEAD", check=False).strip() != f"refs/heads/{name}":
            git(d, "checkout", "-q", name)
    else:
        remote = remote_sha(d, f"refs/heads/{name}")
        if remote:
            net_git(d, "fetch", "-q", "origin", f"refs/heads/{name}")
            git(d, "checkout", "-q", "-b", name, "FETCH_HEAD")
        else:
            git(d, "checkout", "-q", "-b", name, main_sha)
    return git(d, "merge-base", "HEAD", main_sha).strip()


def _on_branch(repo: str, run_id: str) -> Path:
    """Return Phoenix's clone, checked out on the run branch (which must exist already)."""
    name = branch_name(run_id)
    d = clone_dir(repo)
    if git(d, "symbolic-ref", "-q", "HEAD", check=False).strip() != f"refs/heads/{name}":
        clean(d)
        git(d, "checkout", "-q", name)
    return d


# ------------------------------------------------------------- 2. the plan commit
def plan_path_in_repo(run_id: str) -> str:
    """Return where the run's plan is kept inside the project: .phoenix/runs/<run-id>/plan.md."""
    branch_name(run_id)
    return f".phoenix/runs/{run_id}/plan.md"


def commit_plan(repo: str, run_id: str, plan_path: Path) -> str:
    """Copy the plan into the run branch and commit it (the first commit of every run). Return HEAD.

    If the same plan is already committed (a restarted run), nothing new is committed.
    """
    d = _on_branch(repo, run_id)
    rel = plan_path_in_repo(run_id)
    dest = d / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan_path, dest)
    git(d, "add", "--", rel)
    if git(d, "diff", "--cached", "--name-only").strip():
        git(d, *IDENT, "commit", "-q", "-m", f"Phoenix run {run_id}: plan")
    return head(d)


# ------------------------------------------------------------- 3. workspaces
def _strip_hooks(dest: Path) -> None:
    """Remove .git/hooks from a fresh clone, so nothing in it runs by itself."""
    rmtree(dest / ".git" / "hooks")


def fresh_workspace(repo: str, run_id: str, step: int | str, try_no: int) -> Path:
    """Make a new clone of the run branch's head for the builder: cache/work/<run>-<step>-<try>/.

    It has no .git/hooks and no origin. Borrowed from Phoenix 0.6.0 hands/workspace.py:73 (make_work).
    """
    name = branch_name(run_id)
    src = clone_dir(repo)
    dest = work_root() / f"{run_id}-{int(step)}-{int(try_no)}"
    rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "clone", "-q", "--no-hardlinks", "--template=", "-b", name, "--", str(src), dest.name)
    git(dest, "remote", "remove", "origin")
    git(dest, "config", "user.name", "Phoenix builder")
    git(dest, "config", "user.email", "builder@phoenix.local")
    _strip_hooks(dest)
    return dest


def remove_workspace(path: Path) -> None:
    """Delete a workspace or check checkout after a try. Refuses folders outside cache/work/."""
    path = Path(path)
    root = work_root().resolve()
    if path.is_symlink() or path.resolve().parent != root:
        raise GitError(f"{path} is not a Phoenix workspace (those live directly in {root}); not deleting it.")
    rmtree(path)


# ------------------------------------------------------------- 4. snapshot
def _skipped(rel: str) -> bool:
    """True for paths the snapshot never copies back (.git, node_modules, test output folders)."""
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return True
    return any(rel == s or rel.startswith(s + "/") for s in SKIP_PATHS)


def _clear_tracked(d: Path) -> None:
    """Delete every tracked file in the clone's working tree, then any folders left empty."""
    for rel in git(d, "ls-files", "-z").split("\0"):
        if rel and not _skipped(rel):
            p = d / rel
            if p.is_file() or p.is_symlink():
                p.unlink()
    for root, dirs, files in os.walk(d, topdown=False):
        rel = Path(root).relative_to(d)
        if rel.parts[:1] == (".git",) or root == str(d):
            continue
        if not os.listdir(root):
            os.rmdir(root)


def _copy_file(src: Path, dest: Path, mode: int) -> None:
    """Copy one regular file without following a symlink at the source."""
    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    os.chmod(dest, 0o755 if mode & stat.S_IXUSR else 0o644)


def _copy_tree(src_root: Path, dest_root: Path, rel: str = "") -> None:
    """Copy the workspace into the clone like rsync: files, folders and symlinks (as links), never following links.

    Skipped folders are left out. Other special files (sockets, pipes) are ignored.
    """
    src_dir = src_root / rel if rel else src_root
    for entry in os.scandir(src_dir):
        child = f"{rel}/{entry.name}" if rel else entry.name
        if _skipped(child):
            continue
        st = entry.stat(follow_symlinks=False)
        dest = dest_root / child
        if stat.S_ISLNK(st.st_mode):
            os.symlink(os.readlink(entry.path), dest)
        elif stat.S_ISDIR(st.st_mode):
            if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
                raise Rejected([f"{child}: cannot be copied back (something else is in the way)"])
            dest.mkdir(exist_ok=True)
            _copy_tree(src_root, dest_root, child)
        elif stat.S_ISREG(st.st_mode):
            _copy_file(Path(entry.path), dest, st.st_mode)


def staged_changes(d: Path) -> list[Change]:
    """List what `git add -A` staged against HEAD, with file modes.

    Uses `git diff --cached --raw` (name-status plus the modes needed to spot
    symlinks and submodules). Borrowed from Phoenix 0.6.0 hands/workspace.py:232.
    """
    out = git(d, "diff", "--cached", "--raw", "-z", "--no-renames", "HEAD")
    parts = out.split("\0")
    changes, i = [], 0
    while i < len(parts) - 1:
        meta = parts[i]
        if not meta.startswith(":"):
            i += 1
            continue
        _, new_mode, _, _, st = meta[1:].split(" ")
        changes.append(Change(status=st[0], path=parts[i + 1], mode=new_mode))
        i += 2
    return changes


def _gitlike(seg: str) -> bool:
    """True for names git may treat as its own folder (.git, git~1, .git::...)."""
    s = seg.lower().rstrip(". ")
    return s in (".git", "git~1") or s.startswith(".git::")


def is_env_file(basename: str) -> bool:
    """True for .env, .env.<anything> and .dev.vars (but not .env.example / .env.sample).

    Borrowed from Phoenix 0.6.0 hands/workspace.py:39.
    """
    b = basename.lower()
    return (b == ".env" or b.startswith(".env.") or b == ".dev.vars") and b not in ENV_EXAMPLES


def _locked(path: str, locked) -> bool:
    """True when the path is in the locked set (an exact file, or anything under a folder ending in /)."""
    p = path.lower()
    for item in locked:
        s = str(item).lower().lstrip("/")
        if (s.endswith("/") and p.startswith(s)) or p == s:
            return True
    return False


def check_allowlist(changes: list[Change], locked=(), new_tools=()) -> list[str]:
    """Return a plain reason for every change the builder is not allowed to make.

    Borrowed from Phoenix 0.6.0 hands/workspace.py:263-287, without the
    allowed_paths and text-extension rules, plus test-tool settings and the
    locked set. `new_tools` lists the test-tool config prefixes (see
    `tools_without_config`) the project has no config for yet: one config of
    such a tool may be added (a new project sets up its own tests). Changing or
    deleting a config is always refused. Locked checks never use these files.
    """
    bad = []
    added = {}
    for c in changes:
        prefix = _config_prefix(c.path)
        if prefix and c.status == "A" and prefix in new_tools:
            added[prefix] = added.get(prefix, 0) + 1
    for c in changes:
        segs = c.path.split("/")
        lsegs = [x.lower() for x in segs]
        base = segs[-1]
        why = None
        if c.mode in ("120000", "160000"):
            why = "symlinks and submodules are not allowed"
        elif c.status != "D" and is_env_file(base):
            why = "environment files are never committed (the values live in the project env file)"
        elif DENY_SEGMENTS_CI.intersection(lsegs) or any(_gitlike(x) for x in segs):
            why = f"'{(DENY_SEGMENTS_CI.intersection(lsegs) or {'.git'}).pop()}/' belongs to Phoenix or the owner"
        elif base.lower() in DENY_BASENAMES_CI:
            why = f"{base} belongs to the owner (agent instruction or config file)"
        elif _config_prefix(c.path) and not (c.status == "A" and added.get(_config_prefix(c.path)) == 1):
            why = f"{base} is test-tool configuration, which the builder may not change"
        elif _locked(c.path, locked):
            why = "this file holds the step's locked checks"
        if why:
            bad.append(f"{c.status} {c.path}: {why}")
    return bad


def _config_prefix(path: str) -> str:
    """Return the test-tool prefix (`vitest.config.`) a path's file name starts with, or ""."""
    base = path.split("/")[-1].lower()
    return next((p for p in DENY_CONFIG_PREFIXES if base.startswith(p)), "")


def tools_without_config(d: Path) -> tuple[str, ...]:
    """Return the test-tool prefixes for which HEAD has no config file anywhere in the repo."""
    tracked = git(d, "ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0")
    have = {_config_prefix(p) for p in tracked if p}
    return tuple(p for p in DENY_CONFIG_PREFIXES if p not in have)


def _scripts(d: Path, spec: str) -> tuple[bool, object]:
    """Read the `scripts` part of a package.json at a git spec (`HEAD:path` or `:path`).

    Returns (exists, scripts). Raises ValueError when the file is not valid JSON.
    """
    p = run_git(d, "show", spec, check=False)
    if p.returncode != 0:
        return False, None
    data = json.loads(p.stdout.decode("utf-8"))
    return True, data.get("scripts") if isinstance(data, dict) else None


def check_package_scripts(d: Path, changes: list[Change]) -> list[str]:
    """Return a reason for every package.json whose `scripts` changed (read and compared as JSON).

    A package.json that did not exist before may be added (a new project needs one).
    """
    bad = []
    for c in changes:
        if c.path.split("/")[-1] != "package.json":
            continue
        try:
            old_exists, old = _scripts(d, f"HEAD:{c.path}")
            new_exists, new = _scripts(d, f":{c.path}")
        except (ValueError, UnicodeDecodeError):
            bad.append(f"{c.status} {c.path}: is not valid JSON, so its scripts cannot be compared")
            continue
        if old_exists and old != new:
            bad.append(f"{c.status} {c.path}: the 'scripts' section changed; the builder may not change scripts")
    return bad


def snapshot(workspace: Path, repo: str, *, locked=(), env_file: Path | None = None) -> list[Change]:
    """Bring the builder's files back into Phoenix's clone and stage them. Return the changes.

    Copies the workspace's files (not .git, node_modules or test output) over
    the clone's working tree, runs `git add -A`, and lists the staged changes.
    The whole snapshot is rejected (raises Rejected, clone reset) when any
    changed path is a symlink or submodule, an env file, owner- or
    Phoenix-owned (.claude/, .github/, CLAUDE.md, .mcp.json, ...), a test-tool
    config (except the first one of a tool, see check_allowlist), a package.json with changed scripts, in the `locked` set, or the
    lock manifest; when a locked check file no longer matches the manifest
    committed at HEAD (checks.verify_lock); or when scan_secrets finds a secret (`sk_live_`, a private key, or, when
    `env_file` is given, one of its values).
    """
    d = clone_dir(repo)
    workspace = Path(workspace)
    if not workspace.is_dir() or workspace.is_symlink():
        raise GitError(f"workspace {workspace} is missing")
    clean(d)
    try:
        _clear_tracked(d)
        _copy_tree(workspace, d)
        drop_tool_agent_files(d)
        p = run_git(d, "add", "-A", check=False)
        if p.returncode != 0:
            raise Rejected([f"git could not stage the files: {p.stderr.decode(errors='replace').strip()}"])
        changes = staged_changes(d)
        # tests/phoenix/manifest.json is only ever written by Phoenix itself (checks.lock)
        bad = check_allowlist(changes, (*locked, LOCK_MANIFEST), tools_without_config(d))
        bad += check_package_scripts(d, changes)
        bad += check_lock(d)
        if bad:
            raise Rejected(bad)
    except (Rejected, OSError) as e:
        clean(d)
        if isinstance(e, OSError):
            raise Rejected([f"the files could not be copied back: {e}"]) from e
        raise
    bad = scan_secrets(repo, env_file)
    if bad:
        raise Rejected(bad)
    return changes


def drop_tool_agent_files(d: Path) -> bool:
    """Delete a root AGENTS.md that only Next.js wrote (see TOOL_AGENTS_MD). Return True if one was.

    Only a file that is not in HEAD is dropped; an owner's AGENTS.md is never
    touched here (changing it is refused by check_allowlist as before).
    """
    f = d / "AGENTS.md"
    if f.is_symlink() or not f.is_file():
        return False
    if git(d, "ls-tree", "--name-only", "HEAD", "--", "AGENTS.md").strip():
        return False
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not TOOL_AGENTS_MD.fullmatch(text):
        return False
    f.unlink()
    return True


def check_lock(d: Path) -> list[str]:
    """Return a reason when the copied-back files break the check lock (the manifest committed at HEAD)."""
    from phoenix import checks       # checks imports this module; imported here to avoid a loop
    try:
        manifest = checks.committed_manifest(d)
        if manifest:
            checks.verify_lock(d, manifest)
    except checks.LockBroken as e:
        return [f"{e.path}: {e} Locked checks may never be changed; the whole snapshot is refused"]
    return []


# ------------------------------------------------------------- 5. secrets
def secret_forms(env_file: Path) -> dict[bytes, str]:
    """Return every way a value from the env file might appear in a file, mapped to its key name.

    The raw value, its JSON-escaped and URL-encoded forms, and its base64
    forms. Values shorter than 8 characters are skipped (they match ordinary
    words). Based on Phoenix 0.6.0 hands/projectenv.py:230-245 (Redactor).
    """
    forms: dict[bytes, str] = {}
    for key, value in read_env_file(env_file).items():
        if len(value) < MIN_SECRET_LEN:
            continue
        raw = value.encode("utf-8")
        b64 = base64.b64encode
        for f in (value, json.dumps(value)[1:-1], quote(value, safe=""), b64(raw).decode().rstrip("="),
                  b64(b" " + raw).decode()[2:].rstrip("="), b64(b"  " + raw).decode()[3:].rstrip("=")):
            if len(f) >= MIN_SECRET_LEN:
                forms.setdefault(f.encode("utf-8"), key)
    return forms


def find_secrets(data: bytes, forms: dict[bytes, str]) -> list[str]:
    """Return plain descriptions of the secrets found in some file contents (key names, never values)."""
    found = sorted({key for form, key in forms.items() if form in data})
    out = [f"the value of {', '.join(found)}"] if found else []
    out += [what for pattern, what in SECRET_PATTERNS if pattern.search(data)]
    return out


def scan_secrets(repo: str, env_file: Path | None) -> list[str]:
    """Check every staged file (added or changed) for secrets. Return the problems found.

    Looks for any value from the project env file, `sk_live_`, and private
    keys. When something is found, Phoenix's clone is reset (`git reset --hard`)
    so nothing of it stays. Borrowed from Phoenix 0.6.0 hands/workspace.py:247.
    """
    d = clone_dir(repo)
    forms = secret_forms(env_file) if env_file and Path(env_file).exists() else {}
    bad = []
    for c in staged_changes(d):
        if c.status == "D":
            continue
        p = run_git(d, "show", f":{c.path}", check=False)
        if p.returncode != 0:
            continue
        found = find_secrets(p.stdout, forms)
        if found:
            bad.append(f"{c.status} {c.path}: contains {' and '.join(found)}")
    if bad:
        clean(d)
    return bad


# ------------------------------------------------------------- 6. step commits
def _clean_message(message: str) -> str:
    """Drop any line that looks like a Phoenix trailer, so only Phoenix's own trailers count."""
    lines = [ln for ln in message.strip().splitlines()
             if not re.match(rf"\s*({TRAILER_RUN}|{TRAILER_STEP})\s*:", ln, re.I)]
    return "\n".join(lines).strip() or "Phoenix step"


def commit_step(repo: str, run_id: str, step: int, message: str) -> str:
    """Commit what the snapshot staged, with `Phoenix-Run` and `Phoenix-Step` trailers. Return the sha.

    A step that changed nothing still gets a (empty) commit, so its pass is recorded.
    """
    name = branch_name(run_id)
    d = clone_dir(repo)
    if git(d, "symbolic-ref", "-q", "HEAD", check=False).strip() != f"refs/heads/{name}":
        raise GitError(f"Phoenix's clone of {repo} is not on {name}; refusing to commit step {step}.")
    body = f"{_clean_message(message)}\n\n{TRAILER_RUN}: {run_id}\n{TRAILER_STEP}: {int(step)}\n"
    git(d, *IDENT, "commit", "-q", "--allow-empty", "--no-verify", "-F", "-", input=body.encode())
    return head(d)


def passed_steps(repo: str, base_sha: str) -> list[int]:
    """Return the step numbers that passed: the Phoenix-Step trailers in `git log base..HEAD`, sorted."""
    d = clone_dir(repo)
    if not re.fullmatch(r"[0-9a-f]{7,64}", base_sha or ""):
        raise GitError(f"'{base_sha}' is not a commit sha")
    fmt = f"%(trailers:key={TRAILER_STEP},valueonly,separator=%x2C)%x1e"
    out = git(d, "log", f"--format={fmt}", f"{base_sha}..HEAD")
    steps: set[int] = set()
    for record in out.split("\x1e"):
        for value in record.strip().split(","):
            if value.strip().isdigit():
                steps.add(int(value.strip()))
    return sorted(steps)


# ------------------------------------------------------------- 7. check checkouts
def fresh_checkout(repo: str, sha: str) -> Path:
    """Make a clean clone of one commit for the check container: cache/work/check-<sha>-<random>/.

    No .git/hooks, no origin. Borrowed from Phoenix 0.6.0 hands/loop.py:803 (fresh_clone).
    """
    if not re.fullmatch(r"[0-9a-f]{7,64}", sha or ""):
        raise GitError(f"'{sha}' is not a commit sha")
    src = clone_dir(repo)
    dest = work_root() / f"check-{sha[:12]}-{_random.token_hex(3)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "clone", "-q", "--no-hardlinks", "--no-checkout", "--template=", "--", str(src), dest.name)
    git(dest, "checkout", "-q", "--detach", sha)
    git(dest, "remote", "remove", "origin", check=False)
    _strip_hooks(dest)
    return dest


# ------------------------------------------------------------- 8. push
def push_branch(path: Path, branch: str) -> None:
    """Push one `phoenix/<run-id>` branch to origin, never forced. Any other name is refused."""
    if not branch.startswith(BRANCH_PREFIX) or branch_name(branch[len(BRANCH_PREFIX):]) != branch:
        raise GitError(f"Phoenix only pushes phoenix/<run-id> branches; refusing to push '{branch}'.")
    net_git(path, "push", "-q", "--no-verify", "origin", f"refs/heads/{branch}:refs/heads/{branch}")


def push(repo: str, run_id: str) -> None:
    """Push the run branch `phoenix/<run-id>` to GitHub. Refuses main or any other ref name."""
    try:
        name = branch_name(run_id)
    except GitError:
        raise GitError(f"Phoenix only pushes phoenix/<run-id> branches; refusing to push '{run_id}'.") from None
    push_branch(clone_dir(repo), name)
