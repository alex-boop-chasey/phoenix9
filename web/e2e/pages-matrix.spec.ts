import { expect, expectNoHorizontalScroll, expectNoRawOutput, test } from "./fixtures"

// Every page at phone and desktop width, dark and light: no sideways scroll, no console errors, key text visible.
const PAGES: [string, string, RegExp][] = [
  ["projects", "/", /Projects/],
  ["new project", "/#/new", /New project/],
  ["import", "/#/import", /Import/],
  ["overview", "/#/p/demo-site/overview", /About/],
  ["overview (merge waiting)", "/#/p/phoenix9/overview", /Current build/],
  ["build ledger", "/#/p/demo-site/build?list=1", /Builds/],
  ["build running", "/#/p/tiny-tool/build", /Stop build/],
  ["build failed", "/#/p/ember-oak/build", /Gallery page/],
  ["build wizard", "/#/p/notes-only/build?new=1", /Start build|Next/],
  ["logs", "/#/p/demo-site/logs", /Logs/],
  ["project settings", "/#/p/demo-site/settings", /Unsaved changes|Project/],
  ["phoenix settings services", "/#/settings", /Phoenix settings/],
  ["phoenix settings models", "/#/settings?tab=models", /Default models/],
  ["phoenix settings updates", "/#/settings?tab=updates", /Update history/],
  ["styles page", "/#/styles", /Colours/],
]
const SIZES: [string, number, number][] = [["390", 390, 844], ["1400", 1400, 900]]

for (const [theme] of [["dark"], ["light"]] as const) {
  for (const [label, width, height] of SIZES) {
    test(`every page at ${label} px, ${theme}`, async ({ page }, info) => {
      test.skip(info.project.name === "phone" && width > 500, "the 1400 px run is done once, in the desktop project")
      test.skip(info.project.name === "desktop" && width < 500, "the 390 px run is done once, in the phone project")
      const errors: string[] = []
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()) })
      page.on("pageerror", (e) => errors.push(String(e)))
      await page.addInitScript((t) => localStorage.setItem("phoenix9-theme", t), theme)
      await page.setViewportSize({ width, height })
      for (const [name, url, text] of PAGES) {
        await page.goto(url)
        await expect(page.getByRole("main").getByText(text).first(), name).toBeVisible()
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
        await expectNoHorizontalScroll(page)
        await expectNoRawOutput(page)
      }
      expect(errors).toEqual([])
    })
  }
}
