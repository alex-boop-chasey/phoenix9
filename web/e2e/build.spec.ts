import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("demo-site lists builds and opens the waiting one", async ({ page }) => {
  await page.goto("/#/p/demo-site/build?list=1")
  await expect(page.getByRole("button", { name: "Start new build" })).toBeEnabled()
  await expect(page.getByText(/pricing/i).first()).toBeVisible()
  await expect(page.getByText(/contact/i).first()).toBeVisible()
  await expect(page.getByText(/blog/i).first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.getByText(/pricing/i).first().click()
  await expect(page).toHaveURL(/run=20261031-100000-pricing-page/)
  await expect(page.getByRole("button", { name: "Acknowledged" })).toBeVisible()
  await expect(page.getByRole("link", { name: /logs/i }).first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("tiny-tool's running build shows a running line", async ({ page }) => {
  await page.goto("/#/p/tiny-tool/build?run=20261101-080000-add-json-output")
  await expect(page.getByText(/running/i).first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
