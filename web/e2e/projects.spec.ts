import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test.beforeEach(async ({ page }) => { await page.goto("/") })

const row = (page: import("@playwright/test").Page, name: string) => page.locator(`[data-row="${name}"]`)

test("home lists the four demo projects", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
  for (const name of ["demo-site", "tiny-tool", "notes-only", "phoenix9"]) {
    await expect(row(page, name)).toBeVisible()
  }
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("rows show path, repo and the three buttons", async ({ page }) => {
  const demo = row(page, "demo-site")
  await expect(demo.locator(".p-path")).toContainText("demo-site")
  await expect(demo.getByRole("button", { name: /Remove/ })).toBeVisible()
  await expect(demo.getByText("Chat")).toBeVisible()
  await expect(demo.getByText("VS Code")).toBeVisible()
  await expect(row(page, "notes-only").getByText("No repo")).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("owner filter leaves only demo-site", async ({ page }) => {
  await page.getByLabel("Owner").selectOption("rebirth-wd")
  await expect(row(page, "demo-site")).toBeVisible()
  await expect(row(page, "tiny-tool")).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("demo-site shows Needs you and the attention toggle groups it", async ({ page }) => {
  await expect(row(page, "demo-site").getByText("Needs you")).toBeVisible()
  await page.getByRole("button", { name: /Needs my attention/ }).click()
  await expect(page.getByText(/^Needs you · \d+/)).toBeVisible()
  await expect(page.getByRole("separator")).toContainText("Everything else")
  await expectNoHorizontalScroll(page)
})

test("clicking a row opens the project", async ({ page }) => {
  await row(page, "tiny-tool").locator(".p-name").click()
  await expect(page).toHaveURL(/#\/p\/tiny-tool/)
})

test("Add project menu offers Create new and Import", async ({ page }) => {
  await page.getByRole("button", { name: "More ways to add a project" }).click()
  await expect(page.getByRole("menuitem", { name: /Import/ })).toBeVisible()
  await page.getByRole("menuitem", { name: /Create new/ }).click()
  await expect(page).toHaveURL(/#\/new/)
  await expect(page.locator("#pf-name")).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("phoenix9 cannot be removed", async ({ page }) => {
  await row(page, "phoenix9").getByRole("button", { name: /Remove/ }).click()
  await expect(page.getByText("phoenix9 can't be removed")).toBeVisible()
  await page.getByRole("button", { name: "Close" }).click()
  await expect(row(page, "phoenix9")).toBeVisible()
})

test("remove a project, then bring it back with Import", async ({ page }) => {
  await row(page, "notes-only").getByRole("button", { name: /Remove/ }).click()
  await expect(page.getByText("Remove notes-only from Phoenix?")).toBeVisible()
  await page.getByRole("button", { name: /Remove from Phoenix/ }).click()
  await expect(row(page, "notes-only")).toHaveCount(0)
  await expect(page.getByText("notes-only removed from Phoenix")).toBeVisible()
  await page.getByRole("button", { name: "Import" }).click()
  await expect(page).toHaveURL(/#\/import/)
  await expect(page.getByText(/Removed earlier \(1\)/)).toBeVisible()
  const card = page.locator('[data-candidate="notes-only"]')
  await expect(card).toBeVisible()
  await card.getByRole("button", { name: /Import/ }).click()
  await expect(page.getByText("notes-only imported")).toBeVisible({ timeout: 30_000 })
  await expect(card).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("import page has the folder box", async ({ page }) => {
  await page.goto("/#/import")
  await expect(page.getByRole("heading", { name: "Import a project" })).toBeVisible()
  await expect(page.getByLabel("Folder")).toBeVisible()
  await expectNoHorizontalScroll(page)
})
