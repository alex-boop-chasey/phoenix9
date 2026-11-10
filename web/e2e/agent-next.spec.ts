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
  await expect(card).toContainText("phoenix9")
  await expect(card).toContainText("client-site")
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
  await expect(card).toContainText("steps.notify.on")
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
