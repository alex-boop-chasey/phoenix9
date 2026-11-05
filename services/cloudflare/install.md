# Adding Cloudflare to a project

Cloudflare hosts the built site (Pages for static sites, Workers for server code) and holds its DNS.
Deploys use the `wrangler` command-line tool.

Tool: run wrangler with `pnpm dlx wrangler@4 ...` (never install it globally, never add it as a dependency
unless the spec asks for a deploy script in package.json).

Config: a `wrangler.toml` (or `wrangler.jsonc`) in the project root with the project `name` (the Pages or
Worker name) and, for Workers, `compatibility_date`. Never write an account id, zone id or token in it.

Read these from the environment; wrangler reads these exact names by itself:
- `CLOUDFLARE_ACCOUNT_ID` (not secret): which Cloudflare account to deploy into.
- `CLOUDFLARE_API_TOKEN` (secret, optional): only needed when the build deploys with wrangler.
- `CLOUDFLARE_ZONE_ID` (not secret, optional): only for DNS changes on the domain.

Never write their values in code or config. List the names in `.env.example` with empty values.

Deploy:
- Static site (the web profile's `dist/`): `pnpm dlx wrangler@4 pages deploy <dist folder>`.
- Worker: `pnpm dlx wrangler@4 deploy`.
Only deploy when the spec asks for it; a build step that just checks the site does not deploy.
