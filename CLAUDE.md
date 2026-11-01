# Phoenix 9

Phoenix 9 is a project manager plus a configurable AI coding harness for one owner (Alex). It creates
project workspaces, runs builds from spec files as a series of small steps (scripts, or one fresh
Claude session each inside a sealed Docker container), asks Alex when it needs him ("Needs you"), and
shows all of it in a dashboard. Every dashboard action is also a `phoenix` command.

- Design: `docs/architecture.md` (names, folders, file formats; follow it exactly). The full specs live
  outside this repo in the project's notes (/srv/projects/phoenix9/notes/specs/).
- Python: system `python3` 3.12+, standard library only; package `phoenix9/`; tests `tests/` (pytest).
- Front end: `web/` (React, TypeScript, Vite, Tailwind, shadcn/ui; pnpm only, versions pinned).
- Check everything with `./check.sh` (and `./check-browser.sh` for Playwright). Never weaken them.
- `reference/` is read-only material for porting (Phoenix V8, proj, project-selector). Never import it.
- Installed copy that actually runs: /opt/phoenix9 (written only by the updater). Never edit it.

## Hard rules (never weaken; each says why)
1. No AI runs in Phoenix's own processes; Claude runs only in step containers. Why: the runner must stay
   a dumb, auditable script that nothing can talk into doing things.
2. Step containers never get the Docker socket, the GitHub token, SSH keys or account service keys.
   Why: a confused agent with those can push, delete or spend; without them it can only edit its worktree.
3. Phoenix trusts only exit codes, files it wrote, reports it read itself and git objects in its own
   worktrees. Why: an agent saying "done" proves nothing.
4. Specs are mounted read-only; locked checks are fingerprinted. Why: the agent must not move the goalposts.
5. Every git command on an untrusted checkout uses `-c core.fsmonitor=false -c core.hooksPath=/dev/null`.
   Why: a worktree can carry config that runs code on the host.
6. The default diff denylist (`.git`, `.github/workflows`, `.env*`, symlinks, submodules, `CLAUDE.md`,
   `.claude/`, `.mcp.json`, locked checks) can be widened per project but never emptied. Why: these are
   the agent's own leash and the places secrets and automation live.
7. Never `claude --bare`. Why: it ignores the OAuth token and the session fails.
8. Secrets never reach logs, command lines or command output. Why: logs are read by people and agents.
9. Tests never touch the real server (Docker, Claude, GitHub, systemd, /srv/projects, /var/lib/phoenix9);
   everything external goes through an adapter with a fake. Why: builds run as a limited user, and tests
   must be safe to run anywhere.

## Style
Small functions, plain names, a one-line plain-English docstring on every public module and function
(Alex does not read code). No frameworks on the Python side. Every CLI command: plain words by default,
`--json` for agents, `--yes` for anything destructive, and a `command` event recording who ran it.
