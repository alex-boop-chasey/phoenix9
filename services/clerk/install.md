# Adding Clerk to a project

Use the Clerk CLI to add Clerk; it does the wiring. Run it with `pnpm dlx clerk@latest ...` (never install it
globally). A run without a terminal is "agent mode" automatically: no prompts, plain output.

Packages (the CLI adds them): web (Astro) profile `@clerk/astro`, pinned version. It needs a server-side
rendering adapter (the project's Node adapter) because sign-in checks run on the server.

Keys: `PUBLIC_CLERK_PUBLISHABLE_KEY` (starts `pk_test_` or `pk_live_`, safe for browser code) and
`CLERK_SECRET_KEY` (secret, server-side only). Read them from the environment; never write their values in code.

Steps:
1. If both keys are in the environment: put them in `.env` (never committed) and run
   `pnpm dlx clerk@latest init` to add the SDK and the wiring, then `pnpm dlx clerk@latest doctor`
   (and `doctor --fix` once if it reports fixable issues).
2. If they are missing: run `pnpm dlx clerk@latest init` anyway. In agent mode it creates a claimable Clerk
   application with temporary development keys and writes them to the env file. Put the claim link and
   instructions it prints in the step summary so Alex can claim the app later with `clerk auth login` from
   his own machine. Do not run `auth login` yourself (it needs a browser).
3. Instance settings (session lifetime and the like): `pnpm dlx clerk@latest config pull` to see them, then
   `config patch --json '...' --dry-run` first, then the same without `--dry-run`.

Never: run `env pull` without `--print`; run `deploy` (it makes the production instance) unless the spec asks.

Webhooks: `CLERK_WEBHOOK_SIGNING_SECRET` (secret, optional) is only needed if the site receives Clerk webhooks;
verify each webhook with the signing secret before trusting it.

Test and live instances have different key pairs: use the test pair while building. List the names in
`.env.example` with empty values.
