import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("global settings shows its sections and the theme toggle works", async ({ page }) => {
  await page.goto("/#/settings")
  for (const t of ["GitHub", "Services", "Default models", "Telegram", "Phoenix updates"]) {
    await expect(page.getByText(t, { exact: true }).first()).toBeVisible()
  }
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
