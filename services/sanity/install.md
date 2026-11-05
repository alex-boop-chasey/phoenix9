# Adding Sanity to a project

Packages:
- web (Astro) profile: `@sanity/astro` and `@sanity/client` (add with pnpm, pinned versions).

Config: read these from the environment; never write their values in code.
- `PUBLIC_SANITY_PROJECT_ID`, `PUBLIC_SANITY_DATASET` (usually `production`) and `PUBLIC_SANITY_API_VERSION` (a date
  such as `2026-03-01`): safe for browser code.
- `SANITY_API_READ_TOKEN` (secret, optional, Viewer role): only for drafts, Visual Editing or private datasets.
- `SANITY_API_WRITE_TOKEN` (secret, optional, Editor role): only if the site saves content. Server-side only.

The site's addresses (local, preview and live) must be added as CORS origins in the Sanity project's API settings.
If the Studio is embedded, set its path (for example `/admin`) in `astro.config.mjs`. List the names in
`.env.example` with empty values.
