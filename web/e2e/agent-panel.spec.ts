import type { Page } from "@playwright/test"
import { expect, expectNoHorizontalScroll, test } from "./fixtures"

// The Phoenix agent panel on the demo server's fake agent session (see tests/demo_server.py).
const PANEL = "Phoenix agent panel"

/** The panel, once it is open. */
function panel(page: Page) {
  return page.locator(`[aria-label="${PANEL}"]`)
}

/** No raw JSON or thinking text anywhere in the panel. */
async function expectNoRawJson(page: Page) {
  const text = await panel(page).innerText()
  expect(text).not.toContain('{"')
  expect(text).not.toContain('"type"')
  expect(text).not.toContain("tool_use")
  expect(text).not.toContain("signature")
}

test("opens with the header button and shows the conversation", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  await expect(panel(page)).toBeVisible()
  await expect(panel(page).getByText("How is demo-site doing?")).toBeVisible()
  await expect(panel(page).getByText("I could not find that file", { exact: false })).toBeVisible()
  await expectNoRawJson(page)
  await page.keyboard.press("Escape")
  await expect(panel(page)).toBeHidden()
})

test("opens with Ctrl+.", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
  await page.keyboard.press("Control+.")
  await expect(panel(page)).toBeVisible()
  await expect(panel(page).getByPlaceholder("Message the Phoenix agent")).toBeFocused()
})

test("sending a message shows it and the agent's reply", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  const box = panel(page).getByPlaceholder("Message the Phoenix agent")
  await box.fill("Please check the pricing page")
  await box.press("Enter")
  await expect(panel(page).getByText("Please check the pricing page")).toBeVisible()
  await expect(panel(page).getByText("Got it. I am looking at that now.")).toBeVisible({ timeout: 10_000 })
  await expectNoRawJson(page)
})

for (const theme of ["dark", "light"]) {
  test(`the panel reads well in the ${theme} theme`, async ({ page }, info) => {
    await page.addInitScript((t) => localStorage.setItem("phoenix9-theme", t), theme)
    await page.goto("/")
    await page.getByRole("button", { name: "Phoenix agent" }).click()
    await expect(panel(page).getByText("How is demo-site doing?")).toBeVisible()
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
    await expectNoHorizontalScroll(page)
    await expectNoRawJson(page)
    const box = await panel(page).boundingBox()
    const view = page.viewportSize()
    expect(box).not.toBeNull()
    if (info.project.name === "phone" && box && view) {
      // Under 720 px the panel is a full-screen sheet.
      expect(box.width).toBeGreaterThanOrEqual(view.width - 1)
      expect(box.height).toBeGreaterThanOrEqual(view.height - 1)
    }
  })
}

test("at phone width the panel fills the screen and the Send button is reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  await expect(panel(page)).toBeVisible()
  const box = await panel(page).boundingBox()
  expect(box?.width ?? 0).toBeGreaterThanOrEqual(389)
  await expect(panel(page).getByRole("button", { name: "Send" })).toBeInViewport()
  await expectNoHorizontalScroll(page)
})
