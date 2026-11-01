import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("creates a project and lands on its Overview", async ({ page }) => {
  await page.goto("/#/new")
  await page.locator("#pf-name").fill("e2e-new")
  await page.getByLabel("Description").fill("Made by the browser test")
  await page.getByRole("radio", { name: "Empty" }).check()
  await page.getByRole("combobox", { name: "Profile" }).click()
  await page.getByRole("option", { name: /python-script/ }).click()

  await page.getByLabel("Name", { exact: true }).last().fill("E2E_KEY")
  await page.getByLabel("Value").last().fill("secret-e2e-value")
  await page.getByRole("button", { name: "Add" }).click()
  await expect(page.getByLabel("Value").first()).toHaveValue("••••••")
  await expect(page.getByLabel("Name", { exact: true }).last()).toHaveValue("")
  await expectNoHorizontalScroll(page)

  await page.getByRole("button", { name: "Create", exact: true }).click()
  await expect(page.getByRole("list", { name: "Progress" })).toBeVisible()
  await expect(page).toHaveURL(/#\/p\/e2e-new\/overview/, { timeout: 30_000 })
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("a bad name shows the message", async ({ page }) => {
  await page.goto("/#/new")
  await page.locator("#pf-name").fill("Bad Name!")
  await expect(page.getByText(/lowercase|letters|name/i).filter({ hasNotText: /^Name$/ }).first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeDisabled()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
