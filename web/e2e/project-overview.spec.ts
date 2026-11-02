import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("demo-site shows the escalation card and Acknowledged clears it", async ({ page }) => {
  await page.goto("/#/p/demo-site/overview")
  await expect(page.getByRole("button", { name: "Acknowledged" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Skip task" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
  await page.getByRole("button", { name: "Acknowledged" }).click()
  await expect(page.getByRole("button", { name: "Acknowledged" })).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("phoenix9 shows the merge card and Send back needs a note", async ({ page }) => {
  await page.goto("/#/p/phoenix9/overview")
  await expect(page.getByText(/changes safety code/i).first()).toBeVisible()
  await page.getByRole("button", { name: "Send back with a note" }).click()
  const send = page.getByRole("button", { name: "Send back", exact: true })
  await expect(send).toBeDisabled()
  await page.getByLabel("Note for the builder").fill("Please add a test")
  await expect(send).toBeEnabled()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("phoenix9 Overview has no updates panel", async ({ page }) => {
  await page.goto("/#/p/phoenix9/overview")
  await expect(page.getByRole("heading", { name: "Current build" })).toBeVisible()
  await expect(page.getByText("Phoenix updates")).toHaveCount(0)
  await expect(page.getByRole("button", { name: /Install update/ })).toHaveCount(0)
  await expectNoHorizontalScroll(page)
})

test("header shows links, Start new build and tabs; About card shows setup", async ({ page }) => {
  await page.goto("/#/p/demo-site/overview")
  await expect(page.getByRole("heading", { name: "demo-site", level: 1 })).toBeVisible()
  const dock = page.getByRole("group", { name: "Open project" })
  await expect(dock.getByText("VS Code")).toBeVisible()
  await expect(page.getByRole("link", { name: "Start new build" })).toBeVisible()
  const tabs = page.getByRole("navigation", { name: "Project tabs" })
  await expect(tabs.getByRole("link", { name: /^Overview/ })).toHaveAttribute("aria-current", "page")
  await expect(page.getByLabel("Chosen at setup")).toBeVisible()
  await expect(page.getByLabel("On this server")).toBeVisible()
  await page.getByRole("link", { name: "Start new build" }).click()
  await expect(page).toHaveURL(/#\/p\/demo-site\/build\?new=1/)
})

test("demo-site shows the Deploy card with its last deploy", async ({ page }) => {
  await page.goto("/#/p/demo-site/overview")
  await expect(page.getByRole("button", { name: "Deploy now" })).toBeVisible()
  await expect(page.getByRole("link", { name: "https://demo-site.example.com" })).toBeVisible()
  await expect(page.getByText(/rolled back: the health check got a 502/)).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
