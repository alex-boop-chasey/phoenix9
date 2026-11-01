import { defineConfig, devices } from "@playwright/test"

// No webServer: check-browser.sh starts the API (and the built app) and sets PHOENIX_E2E_URL.
export default defineConfig({
  testDir: "e2e",
  reporter: "list",
  use: { baseURL: process.env.PHOENIX_E2E_URL, trace: "retain-on-failure" },
  projects: [
    {
      name: "phone",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
})
