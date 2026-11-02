import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

test.beforeEach(async ({ page }) => { await page.goto("/") })

test("home lists the four demo projects", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
  for (const name of ["demo-site", "tiny-tool", "notes-only", "phoenix9"]) {
    await expect(page.getByRole("link", { name, exact: true }).first()).toBeVisible()
  }
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("desktop shows a table, phone shows cards", async ({ page, isMobile }) => {
  await expect(page.getByRole("link", { name: "demo-site", exact: true }).first()).toBeVisible()
  if (isMobile) {
    await expect(page.getByRole("table")).toHaveCount(0)
  } else {
    for (const h of ["Project", "Path", "Repo", "Size", "Chat", "VS Code", "Status"]) {
      await expect(page.getByRole("columnheader", { name: h, exact: true })).toBeVisible()
    }
  }
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("owner filter leaves only demo-site", async ({ page }) => {
  await page.getByRole("combobox", { name: "Owner" }).click()
  await page.getByRole("option", { name: "rebirth-wd" }).click()
  await expect(page.getByRole("link", { name: "demo-site", exact: true }).first()).toBeVisible()
  await expect(page.getByRole("link", { name: "tiny-tool", exact: true })).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("demo-site shows Needs you", async ({ page }) => {
  await expect(page.getByText("Needs you").first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})

test("Create new project opens the form", async ({ page }) => {
  await page.getByRole("link", { name: "Create new project" }).click()
  await expect(page).toHaveURL(/#\/new/)
  await expect(page.locator("#pf-name")).toBeVisible()
  await expectNoHorizontalScroll(page)
  await expectNoRawOutput(page)
})
