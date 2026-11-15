# Adding Neon to a project

Packages:
- web / node profiles: `@neondatabase/serverless` (add with pnpm, pinned version). It talks to Neon over
  HTTPS and WebSockets, so it works everywhere. When the project uses an ORM, also add that ORM's Neon or
  Postgres adapter (for example `@prisma/adapter-neon` for Prisma; Drizzle has its own `drizzle-orm/neon-http`),
  pinned too.
- python profiles: `psycopg[binary]` (add to the requirements file, pinned version).

Config: read these environment variables; never write their values anywhere in the code.
- `DATABASE_URL` (secret): the pooled connection string (its host has `-pooler`). Use it for the app's
  queries. Server-side code only, never in browser code.
- `DATABASE_URL_UNPOOLED` (secret, optional): the direct connection string. Only for migrations.
- `NEON_PROJECT_ID` (optional): only for the Neon CLI and API.

Builds: a project that lists Neon may reach Neon's hosts from the build container, both over HTTPS and
on the Postgres port (5432). Prefer the HTTPS driver in web / node code anyway: it also works on edge and
serverless hosts.

Put the database set-up in one small module (for example `src/lib/db.ts` or `app/db.py`) and list every
name above that the project uses in `.env.example` with empty values. Skip the optional ones the code does
not use.
