# Service keys: what each website project needs (2026-11-05)

Research only. Compares the official docs (checked 2026-11-05) with `code/services/<name>/service.toml`.
Astro rule used throughout: only names starting `PUBLIC_` reach browser code (`import.meta.env.PUBLIC_*`);
everything else stays server-side. "Browser-safe" = fine to ship to visitors' browsers.

## Format gap (affects every service)

Section 4.6 `[[project_keys]]` has only `name` + `secret`. The research below needs three more fields:
`public` (browser-safe, gets the `PUBLIC_` name), `required` (true/false) and `help` (where to find it).
`[[account_settings]]` already has `help`; `project_keys` should match. Also: only openrouter, resend,
sentry and supabase have an `install.md`; clerk, mux, sanity and stripe have none.

---

## Supabase
Docs: https://supabase.com/docs/guides/api/api-keys , https://supabase.com/docs/guides/getting-started/quickstarts/astrojs , https://supabase.com/docs/guides/database/connecting-to-postgres

Supabase renamed its keys: **publishable** (`sb_publishable_...`) replaces `anon`, **secret** (`sb_secret_...`)
replaces `service_role`. The old JWT keys are being deprecated by end of 2026. Their Astro quickstart now uses
`PUBLIC_SUPABASE_URL` + `PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| Project URL | `PUBLIC_SUPABASE_URL` | no | yes | yes | Project > Connect button (or Settings > API Keys) |
| Publishable key | `PUBLIC_SUPABASE_PUBLISHABLE_KEY` | no | yes | yes | Settings > API Keys, starts `sb_publishable_` |
| Secret key | `SUPABASE_SECRET_KEY` | yes | no | optional (server code that skips row security) | Settings > API Keys, starts `sb_secret_` |
| Database connection string | `DATABASE_URL` | yes | no | optional (only for migrations / direct Postgres / ORMs) | Connect button > pick Direct, Session or Transaction pooler; includes the DB password |
| Project ref | `SUPABASE_PROJECT_REF` | no | yes | optional (CLI linking, type generation) | The `xxxx` in `xxxx.supabase.co`; Settings > General |

| Account value | Kind | Notes |
| --- | --- | --- |
| Personal access token (`sbp_...`) | secret, `SUPABASE_ACCESS_TOKEN` | Account > Access Tokens; drives the Management API (create projects, read keys) |
| Organisation | setting | Needed to create a project (org slug/id) |
| Default region | setting (new) | Needed to create a project, e.g. `ap-southeast-2` (Sydney) |

Gaps vs service.toml:
- `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` are the legacy names. Rename to `PUBLIC_SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY`.
- `SUPABASE_URL` should be `PUBLIC_SUPABASE_URL` for Astro.
- Missing optional `DATABASE_URL` and `SUPABASE_PROJECT_REF`.
- Missing account setting: default region. Creating a project also needs a DB password: Phoenix should generate one and store it as a project secret.
- Proxy allow-list has no `POST /v1/projects`, so Phoenix can't create a project yet (fine if "connect existing" only).
- install.md describes the legacy keys; update it.

## Sanity
Docs: https://www.sanity.io/docs/astro/configure-sanity-astro , https://www.sanity.io/docs/content-lake/http-auth , https://www.sanity.io/docs/content-lake/cors

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| Project ID | `PUBLIC_SANITY_PROJECT_ID` | no | yes | yes | sanity.io/manage > the project (shown at top) |
| Dataset | `PUBLIC_SANITY_DATASET` | no | yes | yes | sanity.io/manage > project > Datasets; usually `production` |
| API version | `PUBLIC_SANITY_API_VERSION` | no | yes | yes (can default in code) | Not in the dashboard: a date such as `2026-03-01`; pick today's date |
| Read token | `SANITY_API_READ_TOKEN` | yes | no | optional (drafts, Visual Editing, private datasets) | sanity.io/manage > project > API > Tokens, role Viewer |
| Write token | `SANITY_API_WRITE_TOKEN` | yes | no | optional (forms or scripts that save content) | Same page, role Editor |
| Studio path | (config `studioBasePath`, e.g. `/admin`) | no | yes | optional | Not a key; a setting in `astro.config.mjs` |

Also needed (not a key): CORS origins for the site's URLs (localhost port, preview, live domain), set in
sanity.io/manage > API > CORS Origins or `sanity cors add`.

| Account value | Kind | Notes |
| --- | --- | --- |
| Organisation robot token (or personal token) | secret | Org management console > API > Tokens, developer role; creates projects, datasets, CORS origins, project tokens |
| Organisation ID | setting | Needed to create projects under the right org |

Gaps vs service.toml:
- Names lack `PUBLIC_` (`SANITY_PROJECT_ID`, `SANITY_DATASET`).
- Missing `PUBLIC_SANITY_API_VERSION`.
- One `SANITY_API_TOKEN` should be split into read (Viewer) and write (Editor) tokens, both optional.
- `account_keys = []`: no way for Phoenix to create projects/tokens/CORS origins. Could become store-and-wire with an org token + org ID setting.
- `hosts = ["sanity.io"]` is fine: suffix match covers `<id>.api.sanity.io` and `<id>.apicdn.sanity.io`.
- No install.md.

## Clerk
Docs: https://clerk.com/docs/astro/getting-started/quickstart , https://clerk.com/docs/reference/backend/verify-webhook

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| Publishable key | `PUBLIC_CLERK_PUBLISHABLE_KEY` | no | yes | yes | Clerk Dashboard > API keys > Quick copy (starts `pk_test_` / `pk_live_`) |
| Secret key | `CLERK_SECRET_KEY` | yes | no | yes | Same page; shown once (starts `sk_test_` / `sk_live_`) |
| Webhook signing secret | `CLERK_WEBHOOK_SIGNING_SECRET` | yes | no | optional (only if the site receives Clerk webhooks) | Dashboard > Webhooks > the endpoint > Signing Secret |

Development and production instances have different key pairs (test vs live).

| Account value | Kind | Notes |
| --- | --- | --- |
| None today | - | Clerk has no documented public account-level token for creating applications. Its official MCP server (OAuth) can create apps; Phoenix can't use that headless. Keep keys-only. |

Gaps vs service.toml:
- `CLERK_PUBLISHABLE_KEY` should be `PUBLIC_CLERK_PUBLISHABLE_KEY` (Astro SDK reads that name).
- Missing optional `CLERK_WEBHOOK_SIGNING_SECRET`.
- No install.md (package `@clerk/astro`, needs SSR adapter).
- `hosts = ["api.clerk.com"]`: the browser also talks to the instance's Frontend API (`*.clerk.accounts.dev` in dev, `clerk.<domain>` in prod). Add `clerk.accounts.dev` if tests run sign-in in a step container.

## Stripe
Docs: https://docs.stripe.com/keys

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| Publishable key | `PUBLIC_STRIPE_PUBLISHABLE_KEY` | no | yes | yes | Dashboard > Developers > API keys (`pk_test_` / `pk_live_`) |
| Secret or restricted key | `STRIPE_SECRET_KEY` | yes | no | yes | Same page. Stripe now recommends a restricted key (`rk_...`) with only the needed permissions over the full `sk_...` |
| Webhook signing secret | `STRIPE_WEBHOOK_SECRET` | yes | no | optional (only if the site handles webhooks) | Dashboard > Webhooks > the endpoint > Signing secret (`whsec_...`) |

Sandbox (test) and live mode each have their own keys; objects don't cross between them.

| Account value | Kind | Notes |
| --- | --- | --- |
| Organisation API key (`sk_org_...`) | secret, optional | Only for managing many Stripe accounts at once; not needed for normal sites. Keep keys-only. |

Gaps vs service.toml:
- `STRIPE_PUBLISHABLE_KEY` should be `PUBLIC_STRIPE_PUBLISHABLE_KEY`.
- Help text should steer to a restricted key (`rk_`), and say test keys first.
- `STRIPE_WEBHOOK_SECRET` should be marked optional.
- No install.md (package `stripe` server-side, `@stripe/stripe-js` browser).

## Resend
Docs: https://resend.com/docs/send-with-astro , https://resend.com/docs/api-reference/api-keys/create-api-key

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| API key (sending access) | `RESEND_API_KEY` | yes | no | yes | Resend > API Keys > Create; pick "Sending access" and restrict to the site's domain |
| From address | `RESEND_FROM` | no | no (server only, but not secret) | yes | An address on a domain verified at Resend > Domains; `onboarding@resend.dev` is test-only |
| Webhook signing secret | `RESEND_WEBHOOK_SECRET` | yes | no | optional | Resend > Webhooks > the endpoint |

| Account value | Kind | Notes |
| --- | --- | --- |
| Full-access API key | secret, `RESEND_API_KEY` | Only a `full_access` key can list domains and create per-site keys; a `sending_access` key can only send |
| Send from | setting (exists) | Default sender |

Gaps vs service.toml:
- Same name `RESEND_API_KEY` is used for the account key and the project key. Works, but the account key must be full access and the project key should be a separate sending-only key per site. Say so in help text.
- Proxy allow-list has no `POST /api-keys` / `POST /domains`, so Phoenix can't mint a per-site sending key or add a domain yet.
- Missing optional `RESEND_WEBHOOK_SECRET`.

## Sentry
Docs: https://docs.sentry.io/platforms/javascript/guides/astro/ , https://docs.sentry.io/concepts/key-terms/dsn-explainer/

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| DSN | `PUBLIC_SENTRY_DSN` | no | yes (only allows sending events) | yes | Project Settings > Client Keys (DSN) |
| Org slug | `SENTRY_ORG` | no | no need | yes for source maps | In the URL / Organisation settings |
| Project slug | `SENTRY_PROJECT` | no | no need | yes for source maps | Project Settings > General |
| Auth token (build) | `SENTRY_AUTH_TOKEN` | yes | no | optional (uploads source maps at build time) | Settings > Auth Tokens (org token with release/sourcemap scope) |

Note: Astro config files don't see `.env` automatically; Sentry reads `.env.sentry-build-plugin` or use Vite `loadEnv`.

| Account value | Kind | Notes |
| --- | --- | --- |
| Auth token | secret, `SENTRY_AUTH_TOKEN` (exists) | Personal/internal-integration token with project:read/write to create projects and read DSNs |
| Organisation slug | setting (exists) | |
| Default team | setting (new) | Creating a project needs a team slug (`POST /teams/{org}/{team}/projects/`) |

Gaps vs service.toml:
- `SENTRY_DSN` should be `PUBLIC_SENTRY_DSN` for Astro browser code.
- Missing optional project `SENTRY_AUTH_TOKEN` for source-map upload (a narrow org token, not the account token).
- Missing account setting: default team.
- install.md names `@sentry/node`/`@sentry/react`; for Astro it should be `@sentry/astro`.

## Mux
Docs: https://www.mux.com/docs/core/make-api-requests , https://www.mux.com/docs/guides/secure-video-playback , https://github.com/muxinc/mux-node-sdk

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| Access token ID | `MUX_TOKEN_ID` | yes | no | yes | dashboard.mux.com > Settings > Access Tokens (pick the right environment; Mux Video read/write) |
| Access token secret | `MUX_TOKEN_SECRET` | yes | no | yes | Shown once when the token is made |
| Webhook signing secret | `MUX_WEBHOOK_SECRET` | yes | no | optional | Settings > Webhooks > the endpoint |
| Signing key ID | `MUX_SIGNING_KEY` | no-ish | no | optional (signed/private playback only) | Settings > Signing Keys |
| Signing private key | `MUX_PRIVATE_KEY` | yes | no | optional (signed playback) | Shown once when the signing key is made (base64) |

Playback IDs used in pages are content, not keys. Tokens are per environment (dev/prod) and can't cross.

| Account value | Kind | Notes |
| --- | --- | --- |
| None | - | No org-level token; tokens are per environment. Keep keys-only. |

Gaps vs service.toml:
- Missing optional `MUX_WEBHOOK_SECRET`, `MUX_SIGNING_KEY`, `MUX_PRIVATE_KEY`.
- `MUX_TOKEN_ID` is marked secret; it is more of a username, but keeping it secret is harmless.
- `hosts` should add `stream.mux.com` / `image.mux.com` if tests load video; `api.mux.com` alone covers server calls. No install.md.

## OpenRouter
Docs: https://openrouter.ai/docs/api-reference/authentication , https://openrouter.ai/docs/guides/overview/auth/management-api-keys

| Project value | Env name | Secret | Browser-safe | Req. | Where to find it |
| --- | --- | --- | --- | --- | --- |
| API key | `OPENROUTER_API_KEY` | yes | no | yes | openrouter.ai > Settings > Keys; set a credit limit per key |
| Site URL (attribution) | `OPENROUTER_SITE_URL` | no | no need | optional | Sent as `HTTP-Referer` header; just the site's address |
| Site name (attribution) | `OPENROUTER_SITE_NAME` | no | no need | optional | Sent as `X-OpenRouter-Title` (older docs: `X-Title`) |

| Account value | Kind | Notes |
| --- | --- | --- |
| Management key | secret, new e.g. `OPENROUTER_MANAGEMENT_KEY` | openrouter.ai/settings/management-keys. Creates/limits/deletes per-site API keys via `/api/v1/keys`. Cannot call models. |

Gaps vs service.toml:
- Account key and project key are the same `OPENROUTER_API_KEY`, so every site would share one key with no per-site spend limit. Better: account = management key, project = a per-site key Phoenix creates with a limit.
- If switched: proxy needs `GET/POST/PATCH/DELETE /keys`, and `[check]` should be `GET /keys` (not confirmed whether a management key can call `/key`; check on first use).
- Missing optional attribution values.

## GitHub
Docs: https://docs.github.com/en/rest

| Project value | Env name | Secret | Browser-safe | Req. | Where |
| --- | --- | --- | --- | --- | --- |
| None | - | - | - | - | Repo comes from `.phoenix/project.json` |

| Account value | Kind | Notes |
| --- | --- | --- |
| Token | secret, `GH_TOKEN` (exists) | Fine-grained or classic token with repo + workflow rights |
| Default owner | setting (exists) | |

Gaps vs service.toml: none for keys. (Proxy allow-list has no `POST /user/repos` / `POST /orgs/*/repos`, so repo creation isn't via proxy; fine if Phoenix uses `gh` directly.)

---

## Summary of renames to make

| Service | Today | Should be |
| --- | --- | --- |
| supabase | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | `PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` |
| sanity | `SANITY_PROJECT_ID`, `SANITY_DATASET`, `SANITY_API_TOKEN` | `PUBLIC_SANITY_PROJECT_ID`, `PUBLIC_SANITY_DATASET`, `SANITY_API_READ_TOKEN` (+ `_WRITE_TOKEN`) |
| clerk | `CLERK_PUBLISHABLE_KEY` | `PUBLIC_CLERK_PUBLISHABLE_KEY` |
| stripe | `STRIPE_PUBLISHABLE_KEY` | `PUBLIC_STRIPE_PUBLISHABLE_KEY` |
| sentry | `SENTRY_DSN` | `PUBLIC_SENTRY_DSN` |

Open question for Alex/the build: Phoenix also runs non-Astro profiles (node, python). `PUBLIC_` is Astro-only
(Next uses `NEXT_PUBLIC_`, Vite `VITE_`). Option: store a neutral name plus `public = true`, and let the
profile add its prefix when writing env files. Recommended over hard-coding `PUBLIC_` in service.toml.
