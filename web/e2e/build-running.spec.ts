import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("demo-site: escalation under the failed Builder, Acknowledged clears it", async ({ page }) => {
  await page.goto("/#/p/demo-site/build")
  await expect(page).toHaveURL(/run=20261031-100000-pricing-page/)
  const builder = page.locator("[data-task='2'] [data-step=builder]").last()
  const ack = builder.getByRole("button", { name: "Acknowledged" })
  await expect(ack).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
  await ack.click()
  await expect(page.getByRole("button", { name: "Acknowledged" })).toHaveCount(0)
})

test("tiny-tool: running line, then Stop", async ({ page }) => {
  await page.goto("/#/p/tiny-tool/build")
  await expect(page).toHaveURL(/run=20261101-080000-add-json-output/)
  await expect(page.locator("[data-step] [data-indicator=running]").first()).toBeVisible()
  await expect(page.getByRole("complementary", { name: "Build summary" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Stop build" }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Stop build" }).click()
  await expect(page.getByTestId("result")).toContainText("Stopped")
  await expect(page.getByRole("button", { name: "Stop build" })).toHaveCount(0)
  await expectNoRawOutput(page)
  await expectNoHorizontalScroll(page)
})
