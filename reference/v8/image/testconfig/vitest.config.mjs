// Phoenix v8: the Vitest settings for locked checks. Mounted read-only at
// /phoenix/testconfig/ in check containers; the project's own vitest/vite
// config is never used. No imports, so it loads from outside the project.
export default {
  root: '/workspace',
  test: {
    include: ['tests/phoenix/**/*.test.ts'],
    environment: 'node',
    allowOnly: false,
    passWithNoTests: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
    watch: false,
  },
}
