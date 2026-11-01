# Phoenix v8 core on the VPS

Phoenix runs as one Docker container called `phoenix` (Docker Compose project
`phoenix-v8`, file `deploy/docker-compose.yml`). It checks its plans folder
every 30 seconds, builds each plan step by step in throwaway step containers,
and opens a pull request on GitHub. Phoenix 0.6.0 and its `builder` dashboard
(127.0.0.1:8090) are separate and are not touched.

## First set-up

Run once, as root:

```
bash /docker/phoenix-v8/deploy/install.sh
```

It builds the Phoenix image, creates the four volumes, writes the settings,
asks for the Claude token (from `claude setup-token`) and the GitHub token
(the `rebirth-wd` fine-grained token), starts the service and checks the
step container firewall. Nothing you type is shown on screen. Run it again any
time to change a token: press Enter at a question to keep the saved value.

Where Phoenix keeps things (Docker volumes; on the VPS disk they are under
`/var/lib/docker/volumes/<name>/_data/`):

| Volume           | Inside the container | What is in it                                   |
|------------------|----------------------|-------------------------------------------------|
| `phoenix-plans`  | `/phoenix/plans`     | new plans waiting to be picked up               |
| `phoenix-runs`   | `/phoenix/runs`      | one folder per run, kept forever                |
| `phoenix-config` | `/phoenix/config`    | `phoenix.toml`, `claude.env`, `github.env`, `projects/` |
| `phoenix-cache`  | `/phoenix/cache`     | clones, workspaces, the pnpm store              |

## A new project repo

Create the repo on the `rebirth-wd` account by hand, private, and tick
**Add a README file** so `main` has one commit. Phoenix builds on top of
`main` and never pushes `main` itself, so a repo with no commit at all fails at
the start with "push at least one commit to main first". Plans name it as
`Repo: rebirth-wd/<name>`.

## Drop a plan in

Either way works. The file name must end in `.md`.

- With Hostinger's file manager: upload the plan into
  `/var/lib/docker/volumes/phoenix-plans/_data/`.
- From a terminal on the VPS:

  ```
  docker cp plan.md phoenix:/phoenix/plans/
  ```

Within a minute Phoenix moves the file into a new run folder and sends a
Telegram message if it has a problem. A plan with mistakes is not built: its
run folder gets an `ERROR.txt` that lists them. Fix the plan and drop it in again.

Phoenix builds one run at a time. A plan dropped while another is building
waits until that run ends.

## Read a run

Every run has an id like `20261030-1405-qmzt` (it is in the Telegram message
and in the log).

- Steps and their state:

  ```
  docker exec phoenix python -m phoenix status 20261030-1405-qmzt
  ```

- The summary when a run has ended:
  `/var/lib/docker/volumes/phoenix-runs/_data/<run-id>/summary.md`
  (and `summary.html` next to it), or
  `docker exec phoenix cat /phoenix/runs/<run-id>/summary.md`.
- A rejected plan: `/var/lib/docker/volumes/phoenix-runs/_data/<run-id>/ERROR.txt`.
- Everything else about a run (its log, the step logs, the test reports) is
  in that same run folder: `logs/phoenix.log`, the other files in `logs/`, `3-product/`.

## Stop and restart

From `/docker/phoenix-v8`:

```
docker compose -f deploy/docker-compose.yml stop        # stop
docker compose -f deploy/docker-compose.yml start       # start again
docker compose -f deploy/docker-compose.yml restart     # restart
docker compose -f deploy/docker-compose.yml up -d       # start (or apply changes to the compose file)
```

Phoenix starts again by itself after a VPS reboot or a crash
(`restart: unless-stopped`); it only stays down after you stop it. A run that
was building when Phoenix stopped carries on from its last finished step.

After changing Phoenix's code, rebuild and restart:

```
docker compose -f deploy/docker-compose.yml up -d --build
```

## Logs

- Phoenix's own log (what it picked up, every step, every notification):

  ```
  docker logs phoenix            # all of it
  docker logs -f phoenix         # follow it live (Ctrl-C to stop following)
  ```

  Docker keeps the last 50 MB of it (5 files of 10 MB).
- Each run's log: `/var/lib/docker/volumes/phoenix-runs/_data/<run-id>/logs/phoenix.log`.
- Check the step container firewall at any time:

  ```
  docker exec phoenix python -m phoenix doctor
  ```

  It prints `OK: ...` when all is well.

## Safety notes

- Only the `phoenix` container has Docker control (`/var/run/docker.sock`).
  The step containers it starts never get it, nor the GitHub token.
- No AI runs in the `phoenix` container. Claude only runs in the step containers.
- `claude.env` and `github.env` are readable by root only (mode 0600).

## First run

The Phase 1 gate, 30 October 2026, on this VPS, repo `rebirth-wd/v8-smoke`
(plan: `plans/smoke.md` in the Phoenix repo; the follow-up: `plans/smoke-change.md`).

| | Run 1: `Type: new` (`20261030-0542-uuir`) | Run 2: `Type: change` (`20261030-0556-wqjy`) |
|---|---|---|
| Plan | 3 steps (step 3 For you) | the same plus step 4, contact page |
| Dropped → PR opened | 05:41:58 → 05:50:09 UTC, **8 min 11 s** | 05:55:47 → 06:04:51 UTC, **9 min 4 s** |
| Claude sessions | **5** (2 check writers, 3 builders) | **4** (1 check writer, 3 builders) |
| Cost | **$0.32** ($0.23 in usage.jsonl + $0.09 for the two check writers, see bug 3) | **$0.25** |
| Steps | 1 passed (1 try), 2 passed (2 tries), 3 for you | 1, 2, 4 passed (1 try each), 3 for you |
| Full suite | start skipped (new), end green | start green (merged main), end green |
| Pull request | https://github.com/rebirth-wd/v8-smoke/pull/1 (merged) | https://github.com/rebirth-wd/v8-smoke/pull/2 (open) |

PR #1 was merged at 05:55:15 UTC; `phoenix status` showed `merged` at 05:55:43
(28 seconds). Nothing was fixed by hand after either plan was dropped in.

Done by hand before the first drop, and now part of the set-up above: the
empty repo got its first commit (a README) on `main`.

Bugs the run found, each fixed in Phoenix (with tests) before the gate was called passed:

1. **A new project could not set up its own test tools.** Phoenix refused every
   `vitest.config.*` / `playwright.config.*`, even the first one (found before the
   drop, by reading the code). Now the first config of a tool may be added;
   changing, deleting or adding a second one is still refused. Locked checks
   always run with Phoenix's own configs. The builder prompt also said "never
   touch `scripts` in a package.json", though a new package.json may have them;
   it now says so.
2. **Next.js writes `AGENTS.md` by itself.** Next.js 16.4 creates a root
   `AGENTS.md` ("Generated AGENTS.md for AI agents") whenever `next dev` runs
   under Claude Code. Phoenix refused it as an owner file and threw away step 2's
   first try. Now a *new* root `AGENTS.md` that holds only Next.js's marked
   blocks is left out of the commit; any other `AGENTS.md` is still refused.
   (If you ever add your own `AGENTS.md` to a Next.js project, Next.js will add
   its block to it and the builder's tries will be refused: add
   `agentRules: false` to `next.config` in that case.)
3. **Check-writer sessions were not counted.** Their cost was missing from
   `usage.jsonl`, run.json and the summary (run 1's summary says
   "$0.23 in 3 sessions"; the truth is $0.32 in 5). Every session (check writer,
   builder, usage probe) is now recorded with its role, step and try (run 2
   shows all 4).
4. **A refused try was missing from the run log.** It was only in
   `prompts/<step>-<try>-feedback.md`; `logs/phoenix.log` now says
   "step N: Phoenix refused the changes of try T: <first reason>".

Worth knowing (not bugs): a `Type: change` plan that repeats steps already on
`main` runs them again. Their checks are already there and already pass, so each
costs one short builder session (about $0.05) and an empty commit.
