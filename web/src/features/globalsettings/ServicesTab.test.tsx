import { screen, within } from "@testing-library/react"

import { ServicesTab } from "@/features/globalsettings/ServicesTab"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const ep = { connect: "/x/connect", disconnect: "/x/disconnect" }
const rows = [
  { name: "sentry", title: "Sentry", connected: false, website: "https://sentry.io/tokens", endpoints: ep },
  { name: "github", title: "GitHub", connected: true, website: "https://github.com/settings/tokens", endpoints: ep },
  { name: "claude", title: "Claude", connected: true, endpoints: ep },
]

async function renderRows() {
  mockApi({ "GET /api/global/services": { services: rows } })
  renderWithProviders(<ServicesTab />)
  await screen.findByText("Sentry")
}

const row = (n: string) => within(document.querySelector(`[data-service="${n}"]`) as HTMLElement)

test("unconnected service has Connect and a Website link, no Configure or Disconnect", async () => {
  await renderRows()
  const r = row("sentry")
  expect(r.getByRole("button", { name: "Connect Sentry" })).toBeInTheDocument()
  expect(r.queryByRole("button", { name: /Configure|Disconnect/ })).toBeNull()
  const link = r.getByRole("link", { name: "Sentry website" })
  expect(link).toHaveAttribute("href", "https://sentry.io/tokens")
  expect(link).toHaveAttribute("target", "_blank")
  expect(link).toHaveAttribute("rel", "noopener noreferrer")
})

test("connected service has Configure and Disconnect but no Connect", async () => {
  await renderRows()
  const r = row("github")
  expect(r.getByRole("button", { name: "Configure GitHub" })).toBeInTheDocument()
  expect(r.getByRole("button", { name: "Disconnect GitHub" })).toBeInTheDocument()
  expect(r.queryByRole("button", { name: /^Connect/ })).toBeNull()
})

test("a service with no website shows no link", async () => {
  await renderRows()
  expect(row("claude").queryByRole("link")).toBeNull()
})
