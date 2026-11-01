import { expect, expectNoHorizontalScroll, test } from "./fixtures"
import type { Page } from "@playwright/test"

/** On a phone the filters start folded away; open them. */
async function openFilters(page: Page, isMobile: boolean) {
  if (isMobile) await page.getByRole("button", { name: "Filters", exact: true }).click()
}

test("filter by diff shows coloured lines and a Copy button", async ({ page, isMobile }) => {
  await page.goto("/#/p/demo-site/logs")
  await openFilters(page, isMobile)
  await page.getByRole("button", { name: "diff", exact: true }).click()
  await page.getByRole("button", { name: /diff/i }).filter({ hasNotText: /^diff$/ }).first().click()
  await expect(page.getByText("diff --git").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Copy" })).toBeVisible()
  await expectNoHorizontalScroll(page)
})

test("a deep link preselects the run and kind", async ({ page, isMobile }) => {
  await page.goto("/#/p/demo-site/logs?run=20261031-100000-pricing-page&kind=session")
  await openFilters(page, isMobile)
  await expect(page.getByRole("button", { name: "session", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("combobox", { name: "Run" })).toContainText(/pricing/i)
  await expectNoHorizontalScroll(page)
})
