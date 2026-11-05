import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("Phoenix settings shows health, tabs and services, and the theme toggle works", async ({ page }) => {
  await page.goto("/#/settings")
  await expect(page.getByRole("heading", { name: "Phoenix settings" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Health" })).toBeVisible()
  await expect(page.locator("#healthChips button").first()).toBeVisible()
  await expect(page.getByRole("main").getByRole("link", { name: /^Style ref/ })).toBeVisible()
  for (const t of ["Services", "Models", "Updates"]) {
    await expect(page.getByRole("navigation", { name: "Phoenix settings tabs" }).getByRole("button", { name: new RegExp(`^${t}`) })).toBeVisible()
  }
  await expect(page.getByText(/\d+ of \d+ connected/)).toBeVisible()
  await expect(page.getByText("Not connected").first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)

  const html = page.locator("html")
  await expect(html).toHaveClass(/dark/)
  await page.getByRole("button", { name: "Switch to light theme" }).click()
  await expect(html).not.toHaveClass(/dark/)
  await page.getByRole("button", { name: "Switch to dark theme" }).click()
  await expect(html).toHaveClass(/dark/)
})

test("Configure opens a dialog that asks for the key, and the Models and Updates tabs open", async ({ page }) => {
  await page.goto("/#/settings")
  await page.getByRole("button", { name: /^(Connect|Configure) / }).first().click()
  const dlg = page.getByRole("dialog")
  await expect(dlg).toBeVisible()
  await expect(dlg.getByRole("button", { name: "Cancel" })).toBeVisible()
  await dlg.getByRole("button", { name: "Cancel" }).click()
  await expect(dlg).toBeHidden()

  await page.locator("button.tab", { hasText: "Models" }).click()
  await expect(page).toHaveURL(/tab=models/)
  await expect(page.getByRole("heading", { name: "Default models" })).toBeVisible()
  await expect(page.getByRole("columnheader", { name: "If that's unavailable" })).toBeVisible()
  await expectNoHorizontalScroll(page)

  await page.locator("button.tab", { hasText: "Updates" }).click()
  await expect(page).toHaveURL(/tab=updates/)
  await expect(page.getByRole("heading", { name: "Update history" })).toBeVisible()
  await expectNoHorizontalScroll(page)
})
