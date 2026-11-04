import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("creates a project and shows it ready and opens its Overview", async ({ page }) => {
  await page.goto("/#/new")
  await page.locator("#pf-name").fill("e2e-new")
  await page.getByLabel("Description").fill("Made by the browser test")
  await page.locator("label.tile", { has: page.getByRole("radio", { name: "Empty" }) }).click()
  await page.locator("label.tile", { has: page.getByRole("radio", { name: "Python script" }) }).click()
  await expect(page.getByRole("radio", { name: "Python script" })).toBeChecked()

  await page.getByLabel("Name", { exact: true }).last().fill("E2E_KEY")
  await page.getByLabel("Value").last().fill("secret-e2e-value")
  await page.getByRole("button", { name: "Add" }).click()
  await expect(page.getByRole("complementary", { name: "What Phoenix will make" })).toContainText("/srv/projects/e2e-new")
  await expect(page.getByLabel("Value").first()).toHaveValue("••••••")
  await expect(page.getByLabel("Name", { exact: true }).last()).toHaveValue("")
  await expectNoHorizontalScroll(page)

  await page.getByRole("button", { name: "Create project" }).click()
  await expect(page.getByRole("list", { name: "Progress" })).toBeVisible()
  await expect(page.getByText("e2e-new is ready")).toBeVisible({ timeout: 30_000 })
  await page.getByRole("link", { name: "Open e2e-new" }).dispatchEvent("click") // the toast can sit on top on a phone
  await expect(page).toHaveURL(/#\/p\/e2e-new\/overview/)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("a bad name shows the message", async ({ page }) => {
  await page.goto("/#/new")
  await page.locator("#pf-name").fill("Bad Name!")
  await expect(page.getByText(/lowercase|letters|name/i).filter({ hasNotText: /^Name$/ }).first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Create project" })).toBeDisabled()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("choosing a service adds its key rows and unticking removes the empty ones", async ({ page }) => {
  await page.goto("/#/new")
  const names = page.getByPlaceholder("NAME", { exact: true })
  await page.locator("label.tile", { has: page.getByRole("checkbox", { name: "Clerk" }) }).click()
  await expect(page.getByText("1 selected · adds 2 key rows below")).toBeVisible()
  await expect(names.nth(0)).toHaveValue("CLERK_SECRET_KEY")
  await expect(names.nth(1)).toHaveValue("CLERK_PUBLISHABLE_KEY")
  await expect(page.getByLabel("Value").nth(0)).toHaveAttribute("type", "password")
  await expect(page.getByLabel("Value").nth(1)).toHaveAttribute("type", "text")
  await expect(page.getByRole("complementary", { name: "What Phoenix will make" })).toContainText("2 rows (2 need a value)")
  await expectNoHorizontalScroll(page)

  await page.getByLabel("Value").nth(1).fill("pk_test_123")
  await page.locator("label.tile", { has: page.getByRole("checkbox", { name: "Clerk" }) }).click()
  await expect(names.nth(0)).toHaveValue("CLERK_PUBLISHABLE_KEY")
  await expect(names).toHaveCount(2) // the kept row and the empty one
  await expect(page.getByRole("status")).toContainText("Kept CLERK_PUBLISHABLE_KEY")
})
