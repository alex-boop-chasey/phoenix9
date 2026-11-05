import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test("notes-only: wizard to a queued run, remembered as defaults", async ({ page }) => {
  await page.goto("/#/p/notes-only/build")
  await page.getByRole("button", { name: "Start new build" }).click()
  await expect(page.getByText("Step 1 of 7")).toBeVisible()
  await expectNoHorizontalScroll(page)

  await page.getByRole("radiogroup", { name: "Spec" }).getByText("Reading plan", { exact: true }).click()
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 2 of 7")).toBeVisible()
  await page.getByRole("radiogroup", { name: "Preset" }).getByText("Quick", { exact: true }).click()
  const rail = page.getByRole("list", { name: "Effective steps" })
  await expect(rail).toContainText("Verify")
  await expect(rail.locator("[data-off]")).toContainText("Reviewer")
  await expect(rail.locator("[data-off]")).toContainText("Off in Quick")
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 3 of 7")).toBeVisible()
  await page.locator("[data-step=reviewer]").click()
  await expect(page.locator(".canvas").getByText(/Custom, based on Quick/)).toBeVisible()
  await expect(page.getByRole("switch", { name: "Reviewer" })).toBeChecked()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 4 of 7")).toBeVisible()
  const builder = page.getByRole("group", { name: "Builder" })
  await expect(builder).toBeVisible()
  await expect(page.getByLabel("Model", { exact: true })).toHaveCount(0)
  await builder.getByRole("button", { name: "Model and tools" }).click()
  await expect(builder.getByLabel("Model", { exact: true })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await builder.getByRole("button", { name: "Close" }).click()
  await expectNoHorizontalScroll(page)
  await page.getByRole("button", { name: "Next" }).click()

  await expect(page.getByText("Step 5 of 7")).toBeVisible()
  await page.getByLabel("Tries per task (1 to 10)").fill("2")
  await page.getByRole("radiogroup", { name: "On failure" }).getByText("Pause for me", { exact: true }).click()
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
  await page.getByRole("button", { name: "Start build" }).click()

  await expect(page).toHaveURL(/build\?run=/)
  await expect(page.getByText("Queued: waiting for the runner to pick it up.")).toBeVisible()
  await expect(page.getByRole("complementary", { name: "Build summary" })).toContainText("Queued")
  await expect(page.getByRole("heading", { name: "At the start" })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)

  await page.reload()
  await expect(page.getByText("Queued: waiting for the runner to pick it up.")).toBeVisible()

  await page.getByRole("navigation", { name: "Project tabs" }).getByRole("link", { name: "Settings" }).click()
  await expect(page.getByLabel("Tries per task")).toHaveValue("2")
})

test("every Next lands with the progress header at the top of the screen", async ({ page }) => {
  await page.goto("/#/p/notes-only/build")
  await page.getByRole("button", { name: "Start new build" }).click()
  await page.getByRole("radiogroup", { name: "Spec" }).getByText("Reading plan", { exact: true }).click()
  for (let n = 1; n < 7; n++) {
    await page.getByRole("button", { name: "Next" }).click()
    await expect(page.getByText(`Step ${n + 1} of 7`)).toBeVisible()
    await expect.poll(async () => (await page.getByTestId("wizard-progress").boundingBox())?.y ?? -1).toBeGreaterThanOrEqual(0)
    // At the top below the sticky header, unless the page is too short to scroll that far (then it is at the very end).
    await expect.poll(() => page.evaluate(() => {
      const y = document.querySelector(".wiz")!.getBoundingClientRect().top
      const end = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2
      return y >= 0 && y < window.innerHeight && (y < 140 || end)
    })).toBe(true)
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeFocused()
  }
})
