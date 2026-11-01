Step 10 of 11. Package Phoenix as a Docker Compose project for Hostinger's Docker Manager at `/docker/phoenix-v8/`, beside Open WebUI. 0.6.0 stays untouched. Read CLAUDE.md first.

Pre-conditions (the owner does these first; stop and say which is missing if any is): 4 GB swap is on; a VPS snapshot was taken; `docker run --rm alpine nslookup registry.npmjs.org` answers without a timeout; a token from `claude setup-token` is ready; a fine-grained GitHub PAT made by `rebirth-wd` (resource owner `rebirth-wd`, All repositories, Contents read/write, Pull requests read/write) is ready; the `phoenix-step:0.6.0` image is built on the VPS.

Build:
1. `deploy/Dockerfile.phoenix`: `python:3.12-slim` plus `git`, `docker-cli`, `gh`, `rsync`. Copies the `phoenix/` package and `prompts/`, `image/testconfig/`. No Node, no Claude Code in this image.
2. `deploy/docker-compose.yml`: one service `phoenix`, command `python -m phoenix watch`, `restart: unless-stopped`, `/var/run/docker.sock` mounted (this is the Docker control; it is the only container that has it), volumes `phoenix-plans:/phoenix/plans`, `phoenix-runs:/phoenix/runs`, `phoenix-config:/phoenix/config`, `phoenix-cache:/phoenix/cache`, `PHOENIX_HOME=/phoenix`, memory limit 1g. Per-step containers are started by Phoenix through the socket with the host paths of those volumes, so Phoenix must map its own paths to host paths: read them once from `docker volume inspect` at start.
3. `deploy/install.sh`: builds the Phoenix image, creates the volumes, writes `phoenix.toml` with `telegram_script` pointing at the existing `ph-notify` script if present, creates `/phoenix/config/claude.env` and `github.env` from two prompts (mode 0600, values never echoed), and runs `python -m phoenix doctor` inside the container.
4. `deploy/README.md`: in plain English, how to drop a plan in (Hostinger file manager into the `phoenix-plans` volume path, or `docker cp plan.md phoenix:/phoenix/plans/`), how to read a run (`docker exec phoenix python -m phoenix status <id>`, the `summary.md` path), how to stop and restart, and where logs are.

Done when:
- `docker compose -f deploy/docker-compose.yml config` is valid.
- On the VPS: `docker compose up -d` starts the service; `docker logs phoenix` shows the watch loop; `python -m phoenix doctor` inside it prints OK; 0.6.0's `builder` dashboard still answers on 127.0.0.1:8090.
- A test plan with a deliberate error (gap in step numbers) dropped into the plans volume produces `ERROR.txt` and a Telegram message within one minute.
- Commit "Step 10: deploy".
