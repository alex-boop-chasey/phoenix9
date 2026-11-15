import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ConfigureDialog } from "@/features/globalsettings/ConfigureDialog"
import type { ServiceStatus } from "@/lib/types"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const ep = { connect: "services/openrouter/connect", test: "services/openrouter/test" }
const base: ServiceStatus = {
  name: "openrouter", title: "OpenRouter", connected: true, account_keys: ["OPENROUTER_API_KEY"],
  ends_in: { OPENROUTER_API_KEY: "…abcd" }, endpoints: ep, account_settings: [], can_test: true,
}
const LABEL = "Key for making project keys (optional)"

test("the optional key for making project keys is a masked field sent with Save", async () => {
  const api = mockApi({ "POST /api/services/openrouter/connect": { name: "openrouter", connected: true, checked: "ok", message: "ok" } })
  renderWithProviders(<ConfigureDialog service={{ ...base, make_key: { name: "OPENROUTER_MANAGEMENT_KEY", saved: false } }} onClose={() => {}} />)
  const field = screen.getByLabelText(LABEL)
  expect(field).toHaveAttribute("type", "password")
  await userEvent.type(field, "made-up-management-value")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  const sent = api.calls.find((c) => c.path === "/api/services/openrouter/connect")
  expect(sent?.body).toEqual({ values: { OPENROUTER_MANAGEMENT_KEY: "made-up-management-value" }, settings: {} })
})

test("a saved key for making project keys is sealed and never required", async () => {
  mockApi({})
  renderWithProviders(<ConfigureDialog service={{ ...base, make_key: { name: "OPENROUTER_MANAGEMENT_KEY", saved: true } }} onClose={() => {}} />)
  expect(screen.getByText(LABEL)).toBeInTheDocument()
  expect(screen.queryByLabelText(LABEL)).toBeNull()
  expect(screen.getAllByRole("button", { name: "Replace" })).toHaveLength(2)
})

test("no field when the service has no key for making project keys", () => {
  mockApi({})
  renderWithProviders(<ConfigureDialog service={{ ...base, make_key: null }} onClose={() => {}} />)
  expect(screen.queryByText(LABEL)).toBeNull()
})
