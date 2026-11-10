import { expect, test } from "./fixtures"
import type { Page } from "@playwright/test"

/** Open the new agent's page and send one message. */
async function ask(page: Page, message: string): Promise<void> {
  await page.goto("/#/agent-next")
  await expect(page.getByTestId("agent-next")).toBeVisible()
  await page.getByLabel("Message").fill(message)
  await page.getByRole("button", { name: "Send" }).click()
}

test("the streamed reply appears", async ({ page }) => {
  await ask(page, "hello")
  await expect(page.getByTestId("agent-next")).toContainText("Hello from the demo agent. This reply is scripted.")
})

test("the project card shows", async ({ page }) => {
  await ask(page, "show my projects")
  const card = page.getByTestId("project-cards")
  await expect(card).toBeVisible()
  await expect(card).toContainText("demo-site")
  await expect(card).toContainText("old-experiment")
})

test("go_to really changes the page", async ({ page }) => {
  await ask(page, "go to projects")
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
  await expect(page.getByTestId("agent-next")).toHaveCount(0)
})

test("Approve resumes the run", async ({ page }) => {
  await ask(page, "change a setting")
  const card = page.getByTestId("approval-card")
  await expect(card).toContainText("Build notifications for demo-site")
  await card.getByRole("button", { name: "Approve" }).click()
  await expect(card).toContainText("Approved.")
  await expect(page.getByTestId("agent-next")).toContainText("Done. The change was made.")
})

test("Deny produces the refusal reply", async ({ page }) => {
  await ask(page, "change a setting")
  const card = page.getByTestId("approval-card")
  await card.getByRole("button", { name: "Deny" }).click()
  await expect(card).toContainText("Denied.")
  await expect(page.getByTestId("agent-next")).toContainText("Understood. I did not make the change.")
  await expect(page.getByTestId("agent-next")).not.toContainText("Done. The change was made.")
})

const AGENT = "agent-next"

test("the history lists a conversation and New conversation starts a clean one", async ({ page }) => {
  await ask(page, "hello")
  await expect(page.getByTestId(AGENT)).toContainText("This reply is scripted.")
  const history = page.getByRole("navigation", { name: "Conversations" })
  await expect(history.getByRole("button", { name: /hello/ })).toBeVisible()
  await history.getByRole("button", { name: "New conversation", exact: true }).click()
  await expect(page.getByTestId(AGENT)).not.toContainText("This reply is scripted.")
  await history.getByRole("button", { name: /hello/ }).click()
  await expect(page.getByTestId(AGENT)).toContainText("This reply is scripted.")
})

test("a project card opens the project", async ({ page }) => {
  await ask(page, "show my projects")
  await page.getByTestId("project-cards").getByRole("button", { name: /demo-site/ }).click()
  await expect(page).toHaveURL(/#\/p\/demo-site/)
  await expect(page.getByTestId(AGENT)).toHaveCount(0)
})

test("a message chip sends its message", async ({ page }) => {
  await ask(page, "suggest something")
  const chips = page.getByTestId("suggestion-chips")
  await expect(chips).toBeVisible()
  await chips.getByRole("button", { name: "Show my projects" }).click()
  await expect(page.getByTestId("project-cards")).toContainText("demo-site")
})

test("a link chip opens a dashboard page", async ({ page }) => {
  await ask(page, "suggest something")
  await page.getByTestId("suggestion-chips").getByRole("button", { name: "Open the project list" }).click()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
})

test("Stop ends a long reply and the chat still works", async ({ page }) => {
  await ask(page, "slow reply please")
  const stop = page.getByRole("button", { name: "Stop" })
  await expect(stop).toBeVisible()
  await stop.click()
  await expect(stop).toBeHidden()
  await page.getByLabel("Message").fill("hello")
  await page.getByRole("button", { name: "Send" }).click()
  await expect(page.getByTestId(AGENT)).toContainText("This reply is scripted.")
})

test("a reload in the middle of a reply catches up and finishes it", async ({ page }) => {
  await ask(page, "slow reply please")
  await expect(page.getByTestId(AGENT)).toContainText("Working on it.")
  await page.reload()
  await expect(page.getByTestId(AGENT)).toContainText("Working on it.")
  await expect(page.getByTestId(AGENT)).toContainText("That took a while.", { timeout: 30_000 })
  await expect(page.getByRole("button", { name: "Stop" })).toBeHidden()
})

test("the allowance is shown in words, and no dollar sign is on the page", async ({ page }) => {
  await ask(page, "show my projects")
  await expect(page.getByTestId("allowance")).toContainText("plenty left this month")
  await expect(page.getByTestId("project-cards")).toBeVisible()
  expect(await page.locator("body").innerText()).not.toContain("$")
})

test("the old Agent panel and flame button are still there", async ({ page }) => {
  await page.goto("/#/agent-next")
  await expect(page.getByTestId(AGENT)).toBeVisible()
  await expect(page.getByRole("link", { name: "Phoenix, go to projects" })).toBeVisible()
  await page.getByRole("button", { name: "Phoenix agent" }).click()
  const panel = page.locator('[aria-label="Phoenix agent panel"]')
  await expect(panel).toBeVisible()
  await expect(panel.getByPlaceholder("Message the Phoenix agent")).toBeVisible()
})
