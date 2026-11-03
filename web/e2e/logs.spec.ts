import { expect, expectNoHorizontalScroll, test } from "./fixtures"

test("filter by code changes shows coloured lines and a Copy button", async ({ page }) => {
  await page.goto("/#/p/demo-site/logs")
  await page.getByRole("button", { name: "Code changes", exact: true }).click()
  await page.getByRole("listbox", { name: "Logs" }).getByRole("option").first().click()
  await expect(page.getByText("diff --git").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Copy" })).toBeVisible()
  await expect(page.getByRole("listbox", { name: "Logs" }).getByRole("option", { selected: true })).toHaveCount(1)
  await expectNoHorizontalScroll(page)
})

test("a deep link preselects the build and kind", async ({ page }) => {
  await page.goto("/#/p/demo-site/logs?run=20261031-100000-pricing-page&kind=session")
  await expect(page.getByRole("button", { name: "AI conversation", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("combobox", { name: "Build" })).toContainText(/pricing/i)
  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page.getByRole("button", { name: "AI conversation", exact: true })).toHaveAttribute("aria-pressed", "false")
  await expectNoHorizontalScroll(page)
})
