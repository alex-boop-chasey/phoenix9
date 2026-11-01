import { expect, test } from "@playwright/test"

test("opens the Projects page", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible()
})
