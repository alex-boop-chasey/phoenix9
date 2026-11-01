# Adding Sentry to a project

Packages:
- web / node profiles: `@sentry/node` or `@sentry/react` (add with pnpm, pinned version).
- python profiles: `sentry-sdk` (add to the requirements file, pinned version).

Config: read `SENTRY_DSN`, `SENTRY_ORG` and `SENTRY_PROJECT` from the environment (all public). Start
Sentry only when `SENTRY_DSN` is set, so tests and local runs send nothing. List the names in
`.env.example` with empty values.
