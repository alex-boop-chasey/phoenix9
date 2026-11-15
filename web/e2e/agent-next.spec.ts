import { expect, test } from "./fixtures"
import type { Locator, Page } from "@playwright/test"

// The agent is one panel in two sizes: the side drawer (opened by the top bar's "Phoenix agent" button) and
// full screen (its "Expand to full screen" button, or the old #/agent-next address).

/** The agent panel (both sizes). */
function panel(page: Page): Locator {
  return page.getByTestId("agent-panel")
}

/** The conversation inside the panel. */
function chat(page: Page): Locator {
  return panel(page).getByTestId("agent-conversation")
}

/** Type a message into the panel's message box and send it. */
async function send(page: Page, message: string): Promise<void> {
  await panel(page).getByLabel("Message").fill(message)
  await panel(page).getByRole("button", { name: "Send" }).click()
}

/** Open the agent drawer from the top bar on `start` and send one message. */
async function ask(page: Page, message: string, start = "/#/"): Promise<void> {
  await page.goto(start)
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  await expect(panel(page)).toBeVisible()
  await send(page, message)
}

test("the streamed reply appears", async ({ page }) => {
  await ask(page, "hello")
  await expect(chat(page)).toContainText("Hello from the demo agent. This reply is scripted.")
})

test("the project card shows", async ({ page }) => {
  await ask(page, "show my projects")
  const card = panel(page).getByTestId("project-cards")
  await expect(card).toBeVisible()
  await expect(card).toContainText("demo-site")
  await expect(card).toContainText("old-experiment")
})

test("go_to really changes the page and the panel stays open", async ({ page }) => {
  await ask(page, "go to projects", "/#/p/demo-site")
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
  await expect(panel(page)).toBeVisible()
})

test("Approve resumes the run", async ({ page }) => {
  await ask(page, "change a setting")
  const card = panel(page).getByTestId("approval-card")
  await expect(card).toContainText("Build notifications for demo-site")
  await card.getByRole("button", { name: "Approve" }).click()
  await expect(card).toContainText("Approved.")
  await expect(chat(page)).toContainText("Done. The change was made.")
})

test("Deny produces the refusal reply", async ({ page }) => {
  await ask(page, "change a setting")
  const card = panel(page).getByTestId("approval-card")
  await card.getByRole("button", { name: "Deny" }).click()
  await expect(card).toContainText("Denied.")
  await expect(chat(page)).toContainText("Understood. I did not make the change.")
  await expect(chat(page)).not.toContainText("Done. The change was made.")
})

test("full screen lists a conversation and New conversation starts a clean one", async ({ page }) => {
  await ask(page, "hello")
  await expect(chat(page)).toContainText("This reply is scripted.")
  await panel(page).getByRole("button", { name: "Expand to full screen" }).click()
  const history = panel(page).getByRole("navigation", { name: "Conversations" })
  await expect(history.getByRole("button", { name: /hello/ })).toBeVisible()
  await panel(page).getByRole("button", { name: "New conversation", exact: true }).click()
  await expect(chat(page)).not.toContainText("This reply is scripted.")
  await history.getByRole("button", { name: /hello/ }).click()
  await expect(chat(page)).toContainText("This reply is scripted.")
})

test("the drawer's History menu opens an earlier conversation", async ({ page }) => {
  await ask(page, "hello")
  await expect(chat(page)).toContainText("This reply is scripted.")
  await panel(page).getByRole("button", { name: "New conversation", exact: true }).click()
  await expect(chat(page)).not.toContainText("This reply is scripted.")
  await panel(page).getByRole("button", { name: "History" }).click()
  await page.getByRole("menu", { name: "Earlier conversations" }).getByRole("menuitem", { name: /hello/ }).click()
  await expect(chat(page)).toContainText("This reply is scripted.")
})

test("a project card opens the project", async ({ page }) => {
  await ask(page, "show my projects")
  await panel(page).getByTestId("project-cards").getByRole("button", { name: /demo-site/ }).click()
  await expect(page).toHaveURL(/#\/p\/demo-site/)
})

test("a message chip sends its message", async ({ page }) => {
  await ask(page, "suggest something")
  const chips = panel(page).getByTestId("suggestion-chips")
  await expect(chips).toBeVisible()
  await chips.getByRole("button", { name: "Show my projects" }).click()
  await expect(panel(page).getByTestId("project-cards")).toContainText("demo-site")
})

test("a link chip opens a dashboard page", async ({ page }) => {
  await ask(page, "suggest something", "/#/p/demo-site")
  await panel(page).getByTestId("suggestion-chips").getByRole("button", { name: "Open the project list" }).click()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
})

test("Stop ends a long reply and the chat still works", async ({ page }) => {
  await ask(page, "slow reply please")
  const stop = panel(page).getByRole("button", { name: "Stop" })
  await expect(stop).toBeVisible()
  await stop.click()
  await expect(stop).toBeHidden()
  await send(page, "hello")
  await expect(chat(page)).toContainText("This reply is scripted.")
})

test("a reload in the middle of a reply catches up and finishes it", async ({ page }) => {
  await ask(page, "slow reply please")
  await expect(chat(page)).toContainText("Working on it.")
  await page.reload()
  await expect(chat(page)).toContainText("Working on it.")
  await expect(chat(page)).toContainText("That took a while.", { timeout: 30_000 })
  await expect(panel(page).getByRole("button", { name: "Stop" })).toBeHidden()
})

test("no allowance line while there is plenty left, and no dollar sign is on the page", async ({ page }) => {
  await ask(page, "show my projects")
  await expect(page.getByTestId("allowance")).toHaveCount(0)
  await expect(panel(page).getByTestId("project-cards")).toBeVisible()
  expect(await page.locator("body").innerText()).not.toContain("$")
})

test("the old address opens the agent full screen, and it shrinks and closes", async ({ page }) => {
  await page.goto("/#/agent-next")
  await expect(page).toHaveURL(/#\/$/)
  await expect(panel(page)).toBeVisible()
  await expect(panel(page)).toHaveClass(/\bfull\b/)
  await expect(panel(page).getByPlaceholder("Ask the agent")).toBeVisible()
  await expect(page.getByRole("link", { name: "Phoenix, go to projects" })).toBeVisible()
  await panel(page).getByRole("button", { name: "Shrink to side panel" }).click()
  await expect(panel(page)).not.toHaveClass(/\bfull\b/)
  await panel(page).getByRole("button", { name: "Close" }).click()
  await expect(panel(page)).toBeHidden()
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  await expect(panel(page)).toBeVisible()
})
