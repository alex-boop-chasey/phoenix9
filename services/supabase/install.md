# Adding Supabase to a project

Packages:
- web / node profiles: `@supabase/supabase-js` (add with pnpm, pinned version).
- python profiles: `supabase` (add to the requirements file, pinned version).

Config: read these environment variables; never write their values anywhere in the code.
- `SUPABASE_URL` (public), `SUPABASE_ANON_KEY` (public): safe for browser code.
- `SUPABASE_SERVICE_ROLE_KEY` (secret): server-side code only, never in browser code.

Put the client set-up in one small module (for example `src/lib/supabase.ts`) and list the three names
in `.env.example` with empty values.
