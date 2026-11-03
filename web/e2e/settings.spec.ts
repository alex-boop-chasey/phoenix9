import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("Build section shows Safety badges, saves, explains", async ({ page }) => {
  await page.goto("/#/p/demo-site/settings")
  await expect(page.getByText("Safety").first()).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)

  await page.getByRole("button", { name: "Show the effective step list" }).click()
  await expect(page.getByRole("dialog")).toContainText("The effective step list")
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test("changing the Builder model saves and survives a reload", async ({ page }) => {
  await page.goto("/#/p/demo-site/settings")
  await page.getByRole("button", { name: /builder settings/i }).click()
  await page.getByLabel("Model", { exact: true }).fill("claude-opus-5-5")
  await expect(page.getByText("Unsaved changes")).toBeVisible()
  await page.getByRole("button", { name: "Save build settings" }).click()
  await expect(page.getByText("Saved").first()).toBeVisible()
  await page.reload()
  await page.getByRole("button", { name: /builder settings/i }).click()
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("claude-opus-5-5")
  await expectNoHorizontalScroll(page)
})

test("keys form reveals and hides a secret", async ({ page }) => {
  await page.goto("/#/p/demo-site/settings")
  await expect(page.getByLabel("Value").first()).toBeVisible()
  await page.getByRole("button", { name: "Reveal" }).first().click()
  await expect(page.locator('input[value="re_demo_0123456789abcdef"]')).toBeVisible()
  await page.getByRole("button", { name: "Hide" }).first().click()
  await expect(page.locator('input[value="re_demo_0123456789abcdef"]')).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
