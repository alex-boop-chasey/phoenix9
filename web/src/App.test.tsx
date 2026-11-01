import { screen } from "@testing-library/react"

import App from "@/App"
import { renderWithProviders } from "@/test/render"

test("renders Projects placeholder at /", () => {
  renderWithProviders(<App />, { route: "/" })
  expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument()
})

test("unknown route shows Page not found", () => {
  renderWithProviders(<App />, { route: "/nope/nothing" })
  expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: /back to projects/i })).toHaveAttribute("href", "/")
})

test("/p/demo redirects to the overview tab", () => {
  renderWithProviders(<App />, { route: "/p/demo" })
  expect(screen.getByRole("heading", { name: "demo" })).toBeInTheDocument()
  expect(screen.getByTestId("tab")).toHaveTextContent("overview")
})

test("unknown tab falls back to overview", () => {
  renderWithProviders(<App />, { route: "/p/demo/bogus" })
  expect(screen.getByTestId("tab")).toHaveTextContent("overview")
})
