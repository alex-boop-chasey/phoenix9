# Adding Resend to a project

Packages:
- web / node profiles: `resend` (add with pnpm, pinned version).
- python profiles: `resend` (add to the requirements file, pinned version).

Config: read these from the environment; never write their values in code.
- `RESEND_API_KEY` (secret): use a separate sending-only key for this site, not the account's full-access key.
- `RESEND_FROM` (not secret): the sender address, on a domain verified in Resend.
- `RESEND_WEBHOOK_SECRET` (secret, optional): only if the site receives Resend webhooks.

Send email only from server-side code. List the names in `.env.example` with empty values.
