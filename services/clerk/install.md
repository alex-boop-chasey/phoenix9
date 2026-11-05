# Adding Clerk to a project

Packages:
- web (Astro) profile: `@clerk/astro` (add with pnpm, pinned version). It needs a server-side rendering adapter
  (the project's Node adapter) because sign-in checks run on the server.

Config: read these from the environment; never write their values in code.
- `PUBLIC_CLERK_PUBLISHABLE_KEY` (starts `pk_test_` or `pk_live_`): safe for browser code.
- `CLERK_SECRET_KEY` (secret): server-side only.
- `CLERK_WEBHOOK_SIGNING_SECRET` (secret, optional): only if the site receives Clerk webhooks; verify each webhook
  with the signing secret before trusting it.

Test and live instances have different key pairs: use the test pair while building. List the names in
`.env.example` with empty values.
