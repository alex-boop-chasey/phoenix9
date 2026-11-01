# Plan: v8 smoke site

Type: new
Repo: rebirth-wd/v8-smoke
Stack: Next.js (App Router, TypeScript), pnpm, Vitest, Playwright

## About
A tiny test website that proves Phoenix v8 can build a real project end to end:
a home page and an about page. No styling work is needed beyond something clean and readable.

## Every step
Use pnpm. Pin exact versions. Use `@playwright/test` exactly 1.64.1 (its browsers are already
installed in the build container; do not run `playwright install`).
The project's own tests: `pnpm test` runs Vitest once (`vitest run`, only `*.test.ts` files, never
`*.spec.ts`); `pnpm run test:e2e` runs Playwright (only `*.spec.ts` files under `e2e/`, starting the
site itself); `pnpm run test:all` runs both, Vitest first.

## Step 1: Set up the project
Create a Next.js project in the repo root with TypeScript, Vitest and Playwright set up as described
under "Every step", with `dev`, `build`, `start`, `test`, `test:e2e` and `test:all` scripts in
package.json. The home page (/) shows a main heading with the text "Hello from Phoenix".
Add one small Vitest test and one small Playwright test of your own for the home page.

Done when:
- `pnpm build` finishes without errors
- The home page at / shows a main heading with the text "Hello from Phoenix"
- `pnpm test` runs Vitest and exits with code 0

## Step 2: About page
Add an /about page with a main heading "About Phoenix" and a link with the text "Home" that goes
back to the home page. Add a Playwright test of your own for it under `e2e/`.

Done when:
- The page at /about shows a main heading with the text "About Phoenix"
- The /about page has a link named "Home" that opens the home page at / when clicked
- `pnpm build` still finishes without errors

## Step 3: Point a domain at the deploy
For you: yes
Deploy the site (for example on Vercel or Hostinger) and point a domain or subdomain at it,
then check that the home page loads over HTTPS.
