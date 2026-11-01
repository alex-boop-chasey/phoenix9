# Phoenix v8 core

Phoenix v8 core is a headless program that builds websites from hand-written `plan.md` files. It picks up a plan, builds each step with a Claude Code session inside a firewalled Docker container, checks the result itself, and opens a pull request. There are no screens and no planning phase.

## Repo and language
- Repo: a local git repo in this folder, branch `main`. The GitHub remote `alex-boop-chasey/phoenix-v8` is added at Step 10; until then never push and never create GitHub repos.
- GitHub accounts: the owner's own repos (Phoenix itself, phoenix-harness) live on `alex-boop-chasey`. Every project Phoenix builds (client sites, test sites such as `v8-smoke`) lives on the personal account `rebirth-wd`, so plans use `Repo: rebirth-wd/<name>`. Phoenix's `GH_TOKEN` is one fine-grained PAT made by `rebirth-wd` with resource owner `rebirth-wd` and access to All repositories (Contents and Pull requests read/write), so new project repos need no token change. The owner creates each project repo by hand; Phoenix never creates repos and never touches `alex-boop-chasey`.
- Python 3.12 or newer (the system `python3`), standard library only unless a step says otherwise. One package: `phoenix/`. Tests in `tests/` with pytest.
- Use `.venv/bin/python` for everything. pytest is installed there. The build loop checks each step with `.venv/bin/python -m pytest -q` from the repo root.
- Entry point: `python -m phoenix <command>`. Commands are added step by step.
- Reference code: Phoenix 0.6.0 (repo `alex-boop-chasey/phoenix-harness`, commit bce3d66) is already checked out at `/root/ref/phoenix-0.6.0`. Read it, never edit it, never import from it, never clone it again. Copy functions from it where a step says "borrow"; keep the copied file:line in a comment.
- `BUILD-NOTES.md` is the shared memory between build sessions: decisions, assumptions and manual-check output, one `## Step N` heading per step. Read it at the start, add to it at the end.
- Never edit this file or anything under `build/`.

## Folder layout on the VPS (inside the Phoenix container)
- `/phoenix/plans/` : new `plan.md` files arrive here (one file per plan, any name ending `.md`).
- `/phoenix/runs/<run-id>/` : one folder per run, kept forever.
- `/phoenix/config/` : `phoenix.toml`, `claude.env` (CLAUDE_CODE_OAUTH_TOKEN), `github.env` (GH_TOKEN), `projects/<repo-name>.env` (test keys), `projects/<repo-name>.domains` (allowed hosts).
- `/phoenix/cache/` : pnpm store volume and clones.
In development these live under `./var/` in the repo, set by `PHOENIX_HOME`.

## Hard rules (never weaken)
1. No AI runs in the Phoenix container. Claude only runs inside per-step containers started by Phoenix.
2. Per-step containers never get Docker control, the GitHub token, or `~/.ssh`. They get the Claude token and the project's test env file only.
3. Phoenix trusts only container exit codes, files it wrote itself, test reports it read itself, and git objects in its own clones. Nothing the builder says counts.
4. Checks are written by a separate check-writer session and locked before the builder starts. The builder never edits them.
5. Every git command on an untrusted checkout gets `-c core.fsmonitor=false -c core.hooksPath=/dev/null`.
6. Phoenix pushes only `phoenix/<run-id>` branches. It never pushes `main`, never merges.
7. Never use `claude --bare`: it ignores the OAuth token.
8. No secrets in logs that are written to the run folder: redact values from the project env file.

## Style
- Small functions, plain names, docstrings in plain English (the owner does not read code).
- Every step adds pytest tests for its own logic. `python -m pytest` must pass before a step is reported done.
- No frameworks: no Celery, Redis, asyncio, SQLite ORM. `subprocess`, `json`, `pathlib`, `tomllib`, `hashlib` are enough.
