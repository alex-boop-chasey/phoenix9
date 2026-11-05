# Adding Supabase to a project

Packages:
- web / node profiles: `@supabase/supabase-js` (add with pnpm, pinned version).
- python profiles: `supabase` (add to the requirements file, pinned version).

Config: read these environment variables; never write their values anywhere in the code.
- `PUBLIC_SUPABASE_URL` and `PUBLIC_SUPABASE_PUBLISHABLE_KEY` (key starts `sb_publishable_`): safe for browser code.
  In Astro read them as `import.meta.env.PUBLIC_SUPABASE_URL`. These replace the old `anon` key names.
- `SUPABASE_SECRET_KEY` (secret, starts `sb_secret_`, optional): server-side code only, never in browser code.
  It replaces the old `service_role` key.
- `DATABASE_URL` (secret, optional): only for migrations or direct Postgres access.
- `SUPABASE_PROJECT_REF` (optional): only for CLI linking and type generation.

Put the client set-up in one small module (for example `src/lib/supabase.ts`) and list every name above that
the project uses in `.env.example` with empty values. Skip the optional ones the code does not use.
