import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("demo-site: escalation under the failed Builder, Acknowledged clears it", async ({ page }) => {
  await page.goto("/#/p/demo-site/build")
  await expect(page).toHaveURL(/run=20261031-100000-pricing-page/)
  const builder = page.locator("section", { has: page.getByRole("heading", { name: /^Task 2/ }) }).locator("[data-step=builder]")
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
  await expect(page.locator("[data-step] [data-testid=spinner]").first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Stop", exact: true }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Stop build" }).click()
  await expect(page.getByTestId("run-status")).toContainText("Stopped")
  await expect(page.getByRole("link", { name: "Back to builds" })).toBeVisible()
  await expectNoRawOutput(page)
  await expectNoHorizontalScroll(page)
})
