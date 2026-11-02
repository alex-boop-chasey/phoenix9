# Running Phoenix 9 on the server

This guide is for the person who looks after the server. You do not need to read code.

## What is installed where

Phoenix 9 lives in three places on the server:

| Place | What it is | Who writes to it |
|-------|-----------|------------------|
| `/opt/phoenix9` | The running copy of Phoenix 9 (the code). | Only the updater. Never edit it by hand. |
| `/opt/phoenix9-prev` | The copy from before the last update. This is the way back. | The updater. |
| `/srv/projects/phoenix9` | The working copy where Phoenix 9 builds its own next version. | Phoenix 9 (the build runs). |

Phoenix's own data is kept apart from the code, in `/var/lib/phoenix9`:

| Folder | What is in it |
|--------|---------------|
| `config/` | Settings, including `api.env` (the dashboard port). |
| `secrets/` | Keys (Claude, Telegram, GitHub). Folder is private (0700), files are 0600. |
| `keys/` | Project keys, same privacy. |
| `runs/` | One folder per build run. |
| `logs/` | Logs. |
| `update/` | Update requests, results and the update log. |

An update replaces `/opt/phoenix9` only. Your data in `/var/lib/phoenix9` is never touched.

## First install

Do this once, as root, on a server that has git, python3 (3.12 or newer), node, pnpm, gh and docker.
Copy `install.sh` to the server (or clone the repo somewhere temporary) and run:

```
bash install.sh --tag v9.1
```

Use the release number you want instead of `v9.1`. The installer:

1. checks the tools (a missing Docker is only a warning: the step images cannot be built yet),
2. downloads that release into `/opt/phoenix9`,
3. creates the data folders,
4. copies the Claude and Telegram keys from the old Phoenix V8 set-up (file to file; they are never shown),
   and, when the ufw firewall is on, shows the one rule that lets step containers reach the key proxy
   (Docker bridge to its gateway, ports 47100-47199 only) and asks before adding it (`--yes` adds it
   without asking; `--dry-run` only prints it; `--firewall-only` runs just this part on an installed server),
5. builds the dashboard and runs the checks,
6. installs and starts the two services, and links the `phoenix` command.

It refuses to run if `/opt/phoenix9` already exists. If the build or the checks fail it stops and leaves
the download so you can look at it; to start over, delete `/opt/phoenix9` and run it again.

The dashboard starts on port 8095. When it finishes it prints the next steps:

```
phoenix services connect github --from-stdin   # paste the GitHub token, then press Ctrl-D
phoenix images build                           # build the sealed step images
phoenix doctor                                 # check everything
```

## Updates and rollback

Updates are started from the dashboard (Settings, Update) or with `phoenix update install`.
Phoenix waits until no build is mid-step, downloads the new release next to the old one, runs
its tests, swaps the folders, restarts the services and checks that it is healthy. If the check
fails it puts the old copy back by itself and tells you on Telegram.

To go back by hand: `phoenix update rollback` (or the Rollback button). Doing it twice returns to
where you were. See what happened with `phoenix update status`; the full log is in
`/var/lib/phoenix9/update/` (or `phoenix update log`).

## Starting and stopping

There are two services: `phoenix-runner` (does the builds) and `phoenix-api` (the dashboard).

```
systemctl status phoenix-runner phoenix-api
systemctl restart phoenix-runner phoenix-api
systemctl stop phoenix-api
systemctl start phoenix-api
```

Stopping the runner while a build is running stops that build; it can be resumed from the dashboard.
The update service (`phoenix9-update`) is started only by an update request. It is never enabled.

## Logs

- Service logs: `journalctl -u phoenix-api` and `journalctl -u phoenix-runner` (add `-f` to follow).
- Build runs: `/var/lib/phoenix9/runs/<project>/<run>/`.
- Updates: `/var/lib/phoenix9/update/`.

## Moving the dashboard to port 8090 (and back)

The dashboard starts on 8095 because 8090 belongs to the project selector and 8091 to the old V8 page.
To move it to 8090 once the selector is out of the way:

1. Edit `/var/lib/phoenix9/config/api.env` and change `PHOENIX_API_PORT=8095` to `PHOENIX_API_PORT=8090`.
2. `systemctl restart phoenix-api`

To go back, change the number back to 8095 and restart. Only change the port while nothing else
is using the new one (`ss -ltn` lists the busy ports).

## If an update left Phoenix down

1. Look at the folders: `ls -d /opt/phoenix9*`. If `/opt/phoenix9` is missing but `/opt/phoenix9-prev` is there,
   an update died halfway.
2. Start the repair: `systemctl start phoenix9-update`. It puts the previous copy back and restarts the services.
3. If `/opt/phoenix9` is there but unhealthy, run `phoenix update rollback`.
4. Last resort, with `/opt/phoenix9` missing: `mv /opt/phoenix9-prev /opt/phoenix9`, then
   `systemctl restart phoenix-runner phoenix-api`.
5. Run `phoenix doctor` to confirm all is well.

## Safety notes

- Secrets are stored with mode 0600 in a private folder. They are never printed, put on a command line or logged.
- No AI runs inside Phoenix's own processes. The runner and the dashboard are plain programs. Claude runs only
  inside step containers.
- Step containers are sealed: no Docker access, no GitHub token, no SSH keys, a firewall, and specs read-only.
- Service keys (for example GitHub) never enter a step container. A small key proxy outside the container
  adds the key to the few calls a project is allowed to make.
- The dashboard listens on 127.0.0.1 only; the web server in front of it decides who can reach it.
