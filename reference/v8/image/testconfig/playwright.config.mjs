// Phoenix v8: the Playwright settings for locked checks. Mounted read-only at
// /phoenix/testconfig/ in check containers; the project's own playwright config
// is never used. No imports, so it loads from outside the project.
// Screenshots and traces of failed checks go to /out/test-results.
const port = Number(process.env.PHOENIX_WEB_PORT || 3000)

export default {
  testDir: '/workspace/tests/phoenix',
  testMatch: '**/*.spec.ts',
  outputDir: '/out/test-results',
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: process.env.PHOENIX_WEB_COMMAND || 'pnpm run dev',
    cwd: '/workspace',
    env: { PORT: String(port), HOSTNAME: '127.0.0.1' },
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
}
