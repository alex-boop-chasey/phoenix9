import type { Page } from "@playwright/test"
import { expect, test } from "./fixtures"

// Reply blocks in the demo agent's last message (see DEMO_BLOCKS_TEXT in tests/seed_demo.py).
const PANEL = "Phoenix agent panel"

/** Open the agent panel on the Projects page. */
async function openPanel(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  const panel = page.locator(`[aria-label="${PANEL}"]`)
  await expect(panel).toBeVisible()
  return panel
}

test("project tiles render from live data", async ({ page }) => {
  const panel = await openPanel(page)
  const tiles = panel.getByTestId("card-projects")
  await expect(tiles).toBeVisible()
  await expect(tiles.getByText("demo-site").first()).toBeVisible()
  await expect(panel.getByText("block could not be shown", { exact: false })).toHaveCount(0)
})

test("a choice round trip posts the message and goes read-only", async ({ page }) => {
  const panel = await openPanel(page)
  const choice = panel.getByTestId("block-choice")
  await choice.scrollIntoViewIfNeeded()
  await expect(choice).not.toHaveAttribute("data-readonly", "true")
  await choice.getByRole("radio", { name: /The footer/ }).click()
  await expect(panel.getByText("[Phoenix panel · choice next-step] The footer")).toBeVisible({ timeout: 10_000 })
  await expect(choice).toHaveAttribute("data-readonly", "true")
  await expect(choice.getByRole("radio", { name: /The contact form/ })).toBeDisabled()
})

test("a nav button moves the page and the panel stays open", async ({ page }) => {
  const panel = await openPanel(page)
  const nav = panel.getByTestId("block-nav")
  await nav.scrollIntoViewIfNeeded()
  await nav.getByRole("button", { name: "Open demo-site" }).click()
  await expect(page).toHaveURL(/#\/p\/demo-site\/overview/)
  await expect(panel).toBeVisible()
})
