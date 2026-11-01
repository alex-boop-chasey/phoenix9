# vps-docker

Builds the project's `Dockerfile` (it must sit at the repo root) and runs the site as a Docker container on
this server. The container only listens on `127.0.0.1`; the Cloudflare tunnel reaches it from there.

## What a deploy does
1. Builds the image `phoenix-site-<project>:<commit>`.
2. Starts the new version as `site-<project>-check` on a side port and asks it for `health_path`.
   If it does not answer, the check container is thrown away and **the live site is not touched**.
3. Switches: stops the old `site-<project>-live`, starts the new one on `live_port`.
   **The site is down for a few seconds during this switch.**
4. Phoenix checks the live port once more. If it is unhealthy, the previous image is started again.
   If there was no previous image, the site is down and Phoenix says so in the message.

A preview runs as `site-<project>-preview` on `preview_port` from the run's worktree. It never touches live.

## Set up by hand, once
Phoenix does not touch the tunnel or DNS. Point a tunnel route at `http://127.0.0.1:<live_port>` (and one at the
preview port if you want previews). Put the addresses in `public_url` and `preview_url` so messages show them.
`live_port` must be set in `[deploy.settings]`; `side_port` and `preview_port` default to +1000 and +2000.

## Reading the logs
- Deploy log: the run's `logs/deploy.log` (or `logs/deploy-<project>.log`) lists every docker command.
- The site itself: `docker logs site-<project>-live` (kept to 3 files of 10 MB).
- Each attempt: `<project>/.phoenix/deploys.jsonl`, or `phoenix deploy status <project>`.
