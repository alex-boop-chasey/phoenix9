import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("demo-site shows the escalation card and Acknowledged clears it", async ({ page }) => {
  await page.goto("/#/p/demo-site/overview")
  await expect(page.getByRole("button", { name: "Acknowledged" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Skip task" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
  await page.getByRole("button", { name: "Acknowledged" }).click()
  await expect(page.getByRole("button", { name: "Acknowledged" })).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("phoenix9 shows the merge card and Send back needs a note", async ({ page }) => {
  await page.goto("/#/p/phoenix9/overview")
  await expect(page.getByText(/changes safety code/i).first()).toBeVisible()
  await page.getByRole("button", { name: "Send back with a note" }).click()
  const send = page.getByRole("button", { name: "Send back", exact: true })
  await expect(send).toBeDisabled()
  await page.getByLabel("Note for the builder").fill("Please add a test")
  await expect(send).toBeEnabled()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
