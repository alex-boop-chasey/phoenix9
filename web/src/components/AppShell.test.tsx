import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { HashRouter } from "react-router"

import { AppShell } from "@/components/AppShell"
import { info } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const withUpdate = (over: Partial<typeof info.update>) => ({ ...info, update: { ...info.update, ...over } })

test("shows version", async () => {
  mockApi({ "GET /api/info": info })
  renderWithProviders(<AppShell>x</AppShell>)
  expect(await screen.findByText("0.9.0")).toBeInTheDocument()
})

test("update pill hidden when unsupported", async () => {
  mockApi({ "GET /api/info": withUpdate({ supported: false, available: true }) })
  renderWithProviders(<AppShell>x</AppShell>)
  await screen.findByText("0.9.0")
  expect(screen.queryByText("Update available")).toBeNull()
})

test("update pill shown when available", async () => {
  mockApi({ "GET /api/info": withUpdate({ supported: true, available: true }) })
  renderWithProviders(<AppShell>x</AppShell>)
  const pill = await screen.findByText("Update available")
  expect(pill.closest("a")).toHaveAttribute("href", "#/p/phoenix9/overview")
})

test("settings link goes to #/settings", async () => {
  mockApi({ "GET /api/info": info })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <HashRouter>
        <AppShell>x</AppShell>
      </HashRouter>
    </QueryClientProvider>,
  )
  const link = screen.getByRole("link", { name: "Settings" })
  expect(link).toHaveAttribute("href", "#/settings")
})
