# Phoenix 9 web app

React + TypeScript (strict) + Vite + Tailwind + shadcn/ui. **Dark by default** (a toggle switches to light;
the choice is remembered in the browser). pnpm only.

- Develop: `pnpm install`, then `pnpm dev` (proxies `/api` to `http://127.0.0.1:8090`).
- Test: `pnpm test` (Vitest). Browser tests: `pnpm e2e` with `PHOENIX_E2E_URL` set (run by `check-browser.sh`).
- Build: `pnpm build` -> `dist/` (relative asset paths; the app is served under `/proxy/<port>/`).
- Routing is hash based, so it works under any path prefix.

## Pinned versions
react 19.3.1, react-dom 19.3.1, react-router 8.5.1, @tanstack/react-query 5.105.1, vite 8.3.5,
typescript 7.0.2, tailwindcss 4.3.3 (+ @tailwindcss/vite), vitest 5.0.5, jsdom 30.1.3,
@testing-library/react 16.3.3, @playwright/test 1.64.1, radix-ui 1.8.1, lucide-react 1.66.0,
sonner 2.0.8, shadcn CLI 4.23.0 (used with `pnpm dlx`). Exact list: `package.json` and `pnpm-lock.yaml`.
