# Adding Resend to a project

Packages:
- web / node profiles: `resend` (add with pnpm, pinned version).
- python profiles: `resend` (add to the requirements file, pinned version).

Config: read `RESEND_API_KEY` (secret) and `RESEND_FROM` (public, the sender address) from the
environment. Send email only from server-side code. List both names in `.env.example` with empty values.
