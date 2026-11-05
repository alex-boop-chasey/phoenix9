# Adding Mux to a project

Packages:
- server code (web / node profiles): `@mux/mux-node` (add with pnpm, pinned version).
- playing video in a page: `@mux/mux-player` (add with pnpm, pinned version).
- python profiles: `mux_python` (add to the requirements file, pinned version).

Config: read these from the environment, server-side only; never write their values in code.
- `MUX_TOKEN_ID` and `MUX_TOKEN_SECRET`: the access token pair (per environment; do not mix dev and live).
- `MUX_WEBHOOK_SECRET` (secret, optional): only if the site receives Mux webhooks.
- `MUX_SIGNING_KEY` and `MUX_PRIVATE_KEY` (optional): only for signed (private) playback.

Playback IDs shown in pages are content, not keys. List the names in `.env.example` with empty values.
