# Profile images

Each profile has its own Docker image: `profiles/<profile>/image/Dockerfile`. The image tag is the
`image` line in that profile's `profile.toml`.

Build from the repo root (the build context must be the repo root so `COPY image/...` works):

    docker build -f profiles/<p>/image/Dockerfile -t <that profile's image tag> .

| Profile | Tag | Base | Expected size |
|---|---|---|---|
| python-script (build first) | `phoenix9-step-python:1` | python:3.12-bookworm + Node 24 + pytest | about 1.5 GB |
| web (build first) | `phoenix9-step-web:1` | node:24-bookworm + Playwright chromium | about 2.5 GB |
| platform | `phoenix9-step-platform:1` | node:24-bookworm + Python 3 + pnpm | about 1.5 GB |
| research | `phoenix9-step-research:1` | debian:bookworm-slim + Node 24 + python3 + pandoc | about 0.8 GB |
| mobile | `phoenix9-step-mobile:1` | node:24-bookworm + eas-cli + JDK 17 (no Android SDK yet) | about 2 GB |
| desktop | `phoenix9-step-desktop:1` | node:24-bookworm + Rust + Tauri libraries | about 3.5 GB |

Versions live in `image/versions.env`; the `ARG` defaults in each Dockerfile must equal it (a test checks).
Every image keeps the same safety pieces: firewall scripts, a sudoers line for only the firewall script,
`/opt/hands/entry.sh`, a pinned Claude Code, and the non-root user `node` (uid 1000).

Building is done by the chat on the host, never by a run. Sizes are estimates, not measured.

## Using every core in test runs

Check containers (baseline, acceptance, verify, red-check, full-suite) may use every CPU core of the machine;
the global setting `limits.check_cpus` in `global.toml` (`[limits]` table) can be `"all"` (the default) or a number
from 0.5 up to the machine's core count. AI step containers keep their own fixed limit. Each check container gets
the environment variable `PHOENIX_CPUS`, a whole number of at least 1, which a project's test command can use:

    pytest -n "$PHOENIX_CPUS"          # pytest-xdist (the package must be in the project's own requirements)
    vitest run --pool=forks --poolOptions.forks.maxForks="$PHOENIX_CPUS"    # vitest

Phoenix does not change any profile's test command for you.
