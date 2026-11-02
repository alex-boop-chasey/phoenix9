import { execFileSync } from "node:child_process"
import path from "node:path"
import { expect, test as base, type Page } from "@playwright/test"

const ROOT = path.resolve(process.cwd(), "..")

/** Re-seed the demo home and projects folders (the seed script refuses anything that is not a demo folder). */
export function reseed(): void {
  const home = process.env.PHOENIX_E2E_HOME
  const projects = process.env.PHOENIX_E2E_PROJECTS
  if (!home || !projects) throw new Error("PHOENIX_E2E_HOME and PHOENIX_E2E_PROJECTS must be set (run check-browser.sh)")
  execFileSync("python3", [path.join(ROOT, "tests", "seed_demo.py"), home, projects], { stdio: "pipe" })
}

/** Every test starts from fresh demo data, so tests never depend on each other. */
export const test = base.extend<{ fresh: void }>({
  fresh: [async ({}, use) => { reseed(); await use() }, { auto: true }],
})
export { expect }

/** The page must not scroll sideways. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }))
  expect(widths.scroll).toBeLessThanOrEqual(widths.inner)
}

/** No raw output (tracebacks, JSON, diffs) outside the Logs tab. */
export async function expectNoRawOutput(page: Page): Promise<void> {
  const text = await page.locator("body").innerText()
  expect(text).not.toContain("Traceback")
  expect(text).not.toContain('{"ok"')
  expect(text).not.toContain("diff --git")
}
