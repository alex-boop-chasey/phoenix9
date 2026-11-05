# Adding Stripe to a project

Packages:
- server code (web / node profiles): `stripe` (add with pnpm, pinned version).
- browser code: `@stripe/stripe-js` (add with pnpm, pinned version), only if the page needs Stripe Elements.
- python profiles: `stripe` (add to the requirements file, pinned version).

Config: read these from the environment; never write their values in code.
- `PUBLIC_STRIPE_PUBLISHABLE_KEY` (starts `pk_test_` or `pk_live_`): safe for browser code.
- `STRIPE_SECRET_KEY` (secret): server-side only. A restricted key (`rk_...`) with just the needed permissions is
  better than a full secret key.
- `STRIPE_WEBHOOK_SECRET` (secret, optional, `whsec_...`): only if the site handles webhooks; check each webhook's
  signature with it.

Use test-mode keys while building: test and live objects never mix. List the names in `.env.example` with empty values.
