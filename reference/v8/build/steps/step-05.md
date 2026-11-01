Step 5 of 11. Build `phoenix/git.py`: Phoenix's own clone of the project repo, the run branch, fresh workspaces for each try, and the snapshot that brings the builder's work back under Phoenix's control. Read CLAUDE.md first.

All git commands run with `-c core.fsmonitor=false -c core.hooksPath=/dev/null`. Phoenix's own clone lives at `/cache/repos/<repo>/` and is the only `.git` Phoenix trusts. Auth over HTTPS with `GH_TOKEN` from `/config/github.env` through a credential helper script that reads the file; the token is never written into a URL or a workspace.

Build:
1. `ensure_clone(repo)`: clone or fetch `origin/main`. `start_branch(repo, run_id) -> base_sha`: `phoenix/<run-id>` from `origin/main`, idempotent (borrow the idempotent branch logic from 0.6.0 `hands/loop.py:412-439`, without the tags).
2. `commit_plan(repo, run_id, plan_path)`: copies the plan to `.phoenix/runs/<run-id>/plan.md` in the branch and commits it. First commit of every run.
3. `fresh_workspace(repo, run_id, step, try_no) -> path`: a new clone of the branch head into `/cache/work/<run>-<step>-<try>/`, without `.git/hooks`, for the builder container. Borrow `make_work` from `hands/workspace.py:73`. `remove_workspace(path)` after each try.
4. `snapshot(workspace, repo) -> list[Change]`: copies the workspace's files into Phoenix's clone (rsync-like copy, excluding `.git`, `node_modules`, and the Playwright/Vitest output folders), then `git add -A` and `git diff --cached --name-status`. Reject the whole snapshot with a plain reason when any changed path is: a symlink or submodule; `.env*` or `.dev.vars` (borrow `is_env_file` and the deny lists from `hands/workspace.py:21-44`); under `.claude/`, `.github/`, `CLAUDE.md`, `.mcp.json`, `package.json` `scripts` changed (parse and compare), `vitest.config.*`, `playwright.config.*`; or in the locked set (Step 6 supplies it). Borrow `check_allowlist` from `workspace.py:263-287` without the allowed_paths and text-extension branches.
5. `scan_secrets(repo, env_file)`: borrow `hands/workspace.py:247`. Also reject diffs containing `sk_live_` or `-----BEGIN` (private key). On rejection, `git reset --hard` the clone.
6. `commit_step(repo, run_id, step, message)`: commit with trailers `Phoenix-Run: <id>` and `Phoenix-Step: <n>`. `passed_steps(repo, base_sha)`: read those trailers from `git log base..HEAD`. This is the source of truth for which steps passed.
7. `fresh_checkout(repo, sha) -> path`: a clean clone of one commit for the check container (borrow `fresh_clone`, `hands/loop.py:803`).
8. `push(repo, run_id)`: push the run branch only; refuse any other ref name.

Done when:
- pytest uses a local bare repo as `origin`: start a branch, commit a plan, make a workspace, change a file, snapshot, commit with trailers, and `passed_steps` returns the step; a second `start_branch` call changes nothing.
- pytest shows rejection for: a symlink, a `.env` file, a changed `package.json` script, a file containing a value from the env file, a `sk_live_` string.
- pytest shows `push` refuses `main`.
- `python -m pytest` passes. Commit "Step 5: git".
