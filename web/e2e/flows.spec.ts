import { expect, expectNoHorizontalScroll, test } from "./fixtures"

test("the demo data shows every state on the Projects page", async ({ page }) => {
  await page.goto("/")
  const row = (n: string) => page.locator(`[data-row="${n}"]`)
  await expect(row("phoenix9").getByText("Needs you")).toBeVisible()
  await expect(row("tiny-tool").getByText(/Running/)).toBeVisible()
  await expect(row("ember-oak").getByText("Last build failed")).toBeVisible()
  await expect(row("railway-hotel")).toBeVisible()
  await expect(row("notes-only").getByText("No repo")).toBeVisible()
  await expect(page.getByRole("button", { name: /Chat/ })).toHaveCount(0)
  await expect(row("old-experiment")).toHaveCount(0)
  await expect(row("scratch-pad")).toHaveCount(0)
  await page.goto("/#/p/ember-oak/build?list=1")
  await expect(page.getByText("Gallery page").first()).toBeVisible()
  await expect(page.locator("tr", { hasText: "Gallery page" }).getByText(/tasks failed/).first()).toBeVisible()
  await page.goto("/#/import")
  await expect(page.locator("[data-candidate=old-experiment]")).toBeVisible()
  await expect(page.locator("[data-candidate=scratch-pad]")).toBeVisible()
  await expectNoHorizontalScroll(page)
})

test("approve a merge from the review", async ({ page }) => {
  await page.goto("/#/p/phoenix9/overview")
  await page.getByRole("link", { name: "Review and merge" }).click()
  const room = page.locator("[data-review-room]")
  await room.getByRole("button", { name: "Approve & merge" }).click()
  await expect(page.getByText(/Merged into main/).first()).toBeVisible({ timeout: 15_000 })
  await expectNoHorizontalScroll(page)
})

test("configure a service: connected and unconnected rows, then save a key", async ({ page }) => {
  await page.goto("/#/settings")
  await expect(page.getByRole("button", { name: "Configure GitHub" })).toBeVisible()
  await expect(page.getByText("Not connected").first()).toBeVisible()
  await page.getByRole("button", { name: /^Connect / }).first().click()
  const dlg = page.getByRole("dialog")
  const inputs = dlg.locator("input[id^='cf-']")
  const n = await inputs.count()
  for (let i = 0; i < n; i++) await inputs.nth(i).fill("demo-key-0123456789")
  await dlg.getByRole("button", { name: "Save and connect" }).click()
  await expect(dlg).toBeHidden({ timeout: 15_000 })
  await expectNoHorizontalScroll(page)
})

test("answering each kind of question clears 'waiting' everywhere", async ({ page }) => {
  // demo-site: a question card (Skip), no review panel
  await page.goto("/#/p/demo-site/overview")
  await page.getByRole("article", { name: /Needs you/ }).getByRole("button", { name: "Skip task" }).click()
  // The demo server moves the run on at once, so the "Answered" text can be gone before we look: the card must be.
  await expect(page.getByRole("article", { name: /Needs you/ })).toHaveCount(0, { timeout: 15_000 })
  await page.goto("/#/p/demo-site/build")
  await expect(page.getByText(/Waiting for you/)).toHaveCount(0)
  await page.goto("/")
  await expect(page.locator('[data-row="demo-site"]').getByText("Needs you")).toHaveCount(0)

  // phoenix9: the merge, answered in the Build tab
  await page.goto("/#/p/phoenix9/overview")
  await page.getByRole("link", { name: "Review and merge" }).click()
  await page.locator("[data-review-room]").getByRole("button", { name: "Approve & merge" }).click()
  await expect(page.getByText(/Merged into main/).first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/Waiting for you/)).toHaveCount(0)
  await page.goto("/#/p/phoenix9/overview")
  await expect(page.getByRole("link", { name: "Review and merge" })).toHaveCount(0)
  await page.goto("/")
  await expect(page.locator('[data-row="phoenix9"]').getByText("Needs you")).toHaveCount(0)
})

test("the merge review keeps its buttons when the review can't load", async ({ page }) => {
  await page.route("**/api/gates/*/review", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ ok: false, error: "git is busy" }) }))
  await page.goto("/#/p/phoenix9/overview")
  await page.getByRole("link", { name: "Review and merge" }).click()
  const room = page.locator("[data-review-room]")
  await expect(room.getByText(/Couldn't load the changes/)).toBeVisible()
  await expect(room.getByRole("button", { name: "Approve & merge" })).toBeVisible()
  await expect(room.getByRole("button", { name: "Send back" })).toBeVisible()
  await expect(room.getByRole("button", { name: "Don't merge" })).toBeVisible()
})
