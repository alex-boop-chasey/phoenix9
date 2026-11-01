import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("notes-only: wizard to a queued run, remembered as defaults", async ({ page }) => {
  await page.goto("/#/p/notes-only/build")
  await page.getByRole("button", { name: "Start new build" }).click()
  await expect(page.getByText("Step 1 of 7")).toBeVisible()
  await expectNoHorizontalScroll(page)

  await page.getByRole("combobox", { name: "Spec" }).click()
  await page.getByRole("option", { name: /Reading plan/ }).click()
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 2 of 7")).toBeVisible()
  await page.getByRole("radio", { name: "Quick" }).click()
  await expect(page.getByRole("switch", { name: "Verify" })).toBeChecked()
  await expect(page.getByRole("switch", { name: "Reviewer" })).not.toBeChecked()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 3 of 7")).toBeVisible()
  await page.getByRole("switch", { name: "Reviewer" }).click()
  await expect(page.getByText(/Custom, based on Quick/)).toBeVisible()
  await expect(page.getByRole("switch", { name: "Reviewer" })).toBeChecked()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 4 of 7")).toBeVisible()
  await expect(page.getByRole("button", { name: "Builder settings" })).toBeVisible()
  await expect(page.getByLabel("Model", { exact: true })).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 5 of 7")).toBeVisible()
  await page.getByLabel("Tries per task (1 to 10)").fill("2")
  await page.getByRole("radio", { name: "Pause for me" }).click()
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 6 of 7")).toBeVisible()
  await expect(page.getByText("Deployers come later.")).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 7 of 7")).toBeVisible()
  const plan = page.getByRole("region", { name: "Plan" })
  await expect(plan.locator("[data-step=reviewer]")).toHaveAttribute("data-on", "true")
  await expect(page.locator('[data-fact="Tries per task"] dd')).toHaveText("2")
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Submit" }).click()

  await expect(page).toHaveURL(/build\?run=/)
  await expect(page.getByText("Queued: waiting for the runner to pick it up.")).toBeVisible()
  await expect(page.getByTestId("run-status")).toContainText("Queued")
  await expect(page.getByRole("heading", { name: "At the start" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)

  await page.reload()
  await expect(page.getByText("Queued: waiting for the runner to pick it up.")).toBeVisible()

  await page.getByRole("tab", { name: "settings" }).click()
  await expect(page.getByLabel("Tries per task")).toHaveValue("2")
})
