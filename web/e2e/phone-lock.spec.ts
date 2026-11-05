import type { Page } from "@playwright/test"
import { expect, test } from "./fixtures"

// Phone only: pages stay locked to the screen, the tab bar and the Add project menu behave.
const PAGES = [
  "/", "/#/new", "/#/import", "/#/p/demo-site/overview", "/#/p/phoenix9/overview", "/#/p/demo-site/build?list=1",
  "/#/p/tiny-tool/build", "/#/p/ember-oak/build", "/#/p/notes-only/build?new=1", "/#/p/demo-site/logs",
  "/#/p/demo-site/settings", "/#/settings", "/#/settings?tab=models", "/#/settings?tab=updates",
]

/** Elements sticking out past the right edge of the screen that no scroll box of their own contains. */
async function overflowing(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const vw = window.innerWidth
    const out: string[] = []
    const inScrollBox = (el: Element) => {
      for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX
        if (o !== "visible") return true
      }
      return false
    }
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      const cs = getComputedStyle(el)
      if (cs.display === "none" || cs.visibility === "hidden" || cs.position === "fixed") continue
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.right > vw + 0.5 && !inScrollBox(el)) out.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)} right=${Math.round(r.right)}`)
    }
    return out.slice(0, 8)
  })
}

async function settled(page: Page) {
  await page.waitForLoadState("networkidle")
  const widths = await page.evaluate(() => ({ s: document.documentElement.scrollWidth, b: document.body.scrollWidth, w: window.innerWidth }))
  expect(widths.s).toBeLessThanOrEqual(widths.w)
  expect(widths.b).toBeLessThanOrEqual(widths.w)
}

test.describe("phone lock", () => {
  test.beforeEach(({}, info) => { test.skip(info.project.name !== "phone", "phone only") })

  test("no page is wider than the screen once loaded", async ({ page }) => {
    for (const url of PAGES) {
      await page.goto(url)
      await settled(page)
      expect(await overflowing(page), url).toEqual([])
    }
  })

  test("the Add project menu opens fully on screen", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "More ways to add a project" }).tap()
    const menu = page.getByRole("menu")
    await expect(menu).toBeVisible()
    const box = (await menu.boundingBox())!
    const vw = page.viewportSize()!.width
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(vw)
    await settled(page)
  })

  test("the project tabs all fit and a vertical drag on them does not move the page sideways", async ({ page }) => {
    await page.goto("/#/p/demo-site/settings")
    const tabs = page.getByRole("navigation", { name: "Project tabs" })
    await expect(tabs).toBeVisible()
    for (const name of ["Overview", "Build", "Logs", "Settings"]) {
      const b = (await tabs.getByRole("link", { name }).boundingBox())!
      expect(b.x).toBeGreaterThanOrEqual(0)
      expect(b.x + b.width).toBeLessThanOrEqual(390)
    }
    expect(await tabs.evaluate((n) => getComputedStyle(n).overscrollBehaviorX)).toBe("contain")
    const b = (await tabs.boundingBox())!
    const cdp = await page.context().newCDPSession(page)
    const x = b.x + b.width / 2, y = b.y + b.height / 2
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] })
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + 6, y: y - 60 }] })
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] })
    expect(await page.evaluate(() => window.scrollX)).toBe(0)
    await settled(page)
  })
})
