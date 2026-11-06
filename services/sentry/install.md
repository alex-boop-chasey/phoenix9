# Adding Sentry to a project

Packages:
- web (Astro) profile: `@sentry/astro` (add with pnpm, pinned version) and add `sentry()` to the Astro integrations.
- node profile: `@sentry/node` (add with pnpm, pinned version).
- python profiles: `sentry-sdk` (add to the requirements file, pinned version).

Config: read these from the environment.
- `PUBLIC_SENTRY_DSN` (safe in the browser): start Sentry only when it is set, so tests and local runs send nothing.
- `SENTRY_ORG` and `SENTRY_PROJECT` (optional, not secret) and `SENTRY_AUTH_TOKEN` (optional, secret): only for
  uploading source maps at build time. Astro config files do not read `.env` by themselves, so load them with
  Vite `loadEnv` or use a `.env.sentry-build-plugin` file that is never committed.

List the names in `.env.example` with empty values.

Creating the Sentry project (when the project has no DSN yet): through the Sentry proxy, `POST /teams/<org>/<team>/projects/`
with a JSON body of `name`, `slug` and `platform`; then `GET /projects/<org>/<slug>/keys/` and read the DSN from the
first key. `<org>` and `<team>` come from the Sentry account settings `organisation` and `default_team`. Keep the
trailing slash on both addresses (Sentry answers 404 without it).
