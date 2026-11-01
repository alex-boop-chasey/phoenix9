Step 4 of 11. Build `phoenix/docker.py` and the `image/` folder: one function that starts a fresh firewalled container for a Claude session, and one for a throwaway check container. Read CLAUDE.md first.

Build:
1. Copy unchanged from 0.6.0 into `image/`: `image/Dockerfile`, `image/versions.env`, `image/init-firewall.sh`, `image/hands-dns-conf.sh`, and `container/entry.sh` (as `image/entry.sh`). Do not copy `devcontainer.json` or any `.orig` file. In the Dockerfile set `DISABLE_AUTOUPDATER=1` and copy the Superpowers `test-driven-development` and `verification-before-completion` skills from 0.6.0 `image/skills/` into the image. Tag the image `phoenix-step:0.6.0`.
2. `phoenix/docker.py`: borrow `Mount`, `build_argv`, `_execute`, `kill` and `cleanup_orphans` from 0.6.0 `hands/docker.py:61-196`. Keep the flags: `--rm --init --memory --cpus --pids-limit --security-opt no-new-privileges`, `--cap-add NET_ADMIN,NET_RAW` only when the firewall runs, container names `phoenix-<run>-<step>-<try>-<role>`.
3. `run_claude_container(run_id, step, try_no, role, workspace, prompt_file, env_files, allowed_domains_file, timeout_min) -> Result`: mounts the workspace read-write at `/workspace`, the prompt read-only, the hooks folder read-only, the pnpm store volume, the allowed-domains file read-only where `init-firewall.sh` expects it; passes `claude.env` and the project env with `--env-file`; sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`; runs `entry.sh` then the command from Step 3's `build_command`; returns Step 3's `Result`. The container's `~/.claude/projects` is mounted out to `/runs/<id>/prompts/<step>-<try>-<role>/` so the transcript is kept.
4. `run_check_container(run_id, step, try_no, checkout, command, env_file, allowed_domains_file, timeout_min) -> (exit_code, stdout_path)`: same image and firewall (npm must still be reachable), fresh pnpm volume, no Claude token, `/workspace` from the given checkout, runs one shell command, stdout to a host file. Borrow the output capture from `hands/loop.py:815-851`.
5. `probe_firewall()`: borrow `FIREWALL_PROBE` from `hands/__main__.py:525`: starts a container and confirms example.com is blocked and api.anthropic.com answers. CLI: `phoenix doctor` runs it and prints OK or the failure.
6. Per-project allowed domains: `/config/projects/<repo>.domains` is built from the plan's `Sites the app may contact` line plus the built-ins; write `write_domains_file(plan)`.

Done when:
- `docker build -t phoenix-step:0.6.0 image/` succeeds on this machine.
- `python -m phoenix doctor` prints OK (firewall blocks example.com, allows api.anthropic.com).
- pytest covers `build_argv` output for both roles (no NET_ADMIN on the check container without firewall, no claude.env on the check container, container name format) using the argv list only, no Docker.
- A manual run: `run_check_container` with command `echo hi` returns exit 0 and a file holding `hi`.
- `python -m pytest` passes. Commit "Step 4: containers".
