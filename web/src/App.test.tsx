import { screen } from "@testing-library/react"

import App from "@/App"
import { info, projects } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

beforeEach(() => {
  mockApi({
    "GET /api/info": info,
    "GET /api/projects/demo-site": projects[0],
    "GET /api/gates": [],
    "GET /api/projects": [],
    "GET /api/projects/demo-site/runs": [],
    "GET /api/projects/demo-site/changelog": [],
    "GET /api/events/recent": { events: [], next: 0 },
  })
})
afterEach(() => vi.unstubAllGlobals())

test("renders Projects placeholder at /", () => {
  renderWithProviders(<App />, { route: "/" })
  expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument()
})

test("unknown route shows Page not found", () => {
  renderWithProviders(<App />, { route: "/nope/nothing" })
  expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: /back to projects/i })).toHaveAttribute("href", "/")
})

test("/p/demo-site redirects to the overview tab", async () => {
  renderWithProviders(<App />, { route: "/p/demo-site" })
  expect(await screen.findByRole("heading", { name: "demo-site" })).toBeInTheDocument()
  expect(screen.getByRole("tab", { name: "overview" })).toHaveAttribute("aria-selected", "true")
})

test("unknown tab falls back to overview", async () => {
  renderWithProviders(<App />, { route: "/p/demo-site/bogus" })
  expect(await screen.findByRole("tab", { name: "overview" })).toHaveAttribute("aria-selected", "true")
})
