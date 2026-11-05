import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ThemeToggle } from "@/components/ThemeToggle"
import { resetThemeCache } from "@/lib/theme"

beforeEach(() => {
  localStorage.clear()
  resetThemeCache()
})

test("clicking the toggle switches data-theme between dark and light", async () => {
  render(<ThemeToggle />)
  await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }))
  expect(document.documentElement.dataset.theme).toBe("light")
  await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }))
  expect(document.documentElement.dataset.theme).toBe("dark")
})
