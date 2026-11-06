import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import GlobalSettingsPage from "@/pages/GlobalSettingsPage"
import { globalView, info } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const doctor = {
  ok: false, checked_at: new Date().toISOString(),
  checks: [
    { name: "api", ok: true, detail: "up", fix: "" },
    { name: "claude-token", ok: false, detail: "claude.env is missing", fix: "Add the token." },
  ],
}
const svc = (over: Record<string, unknown>) => ({
  name: "supabase", title: "Supabase", description: "Database.", support: "store-and-wire", connected: false,
  account_keys: ["SUPABASE_ACCESS_TOKEN"], checked: "not checked", checked_at: "", used_by: [], ends_in: {},
  account_settings: [], can_test: true,
  endpoints: { connect: "services/supabase/connect", disconnect: "services/supabase/disconnect", test: "services/supabase/test" },
  ...over,
})
const base = (rows: unknown[] = [], over: Record<string, unknown> = {}) => ({
  "GET /api/global": globalView,
  "GET /api/info": info,
  "GET /api/doctor": doctor,
  "GET /api/global/services": { supported: true, services: rows },
  ...over,
})

describe("GlobalSettingsPage", () => {
  it("shows a chip per health check, red with the reason, and the Style reference link", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("Claude token: claude.env is missing")).toBeInTheDocument()
    expect(screen.getByText("Api")).toBeInTheDocument()
    expect(screen.getByText("1 problem")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /^Style ref/ })).toHaveAttribute("href", "/styles")
  })

  it("Run health check runs the full check", async () => {
    const { calls } = mockApi(base([], { "GET /api/doctor": ({ query }: { query: Record<string, string> }) => ({ ...doctor, mode: query.mode }) }))
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: /Run health check/ }))
    await waitFor(() => expect(calls.some((c) => c.path === "/api/doctor" && c.query.mode === "full")).toBe(true))
  })

  it("lists services with a count, Configure, and Connect or Disconnect", async () => {
    mockApi(base([
      svc({ name: "claude", title: "Claude", connected: true, checked: "ok", used_by: ["alpha"] }),
      svc({ name: "resend", title: "Resend" }),
      svc({ name: "stripe", title: "Stripe", support: "keys-only", connected: true, account_keys: [], endpoints: {} }),
    ]))
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("1 of 2 connected")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Disconnect Claude" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Connect Resend" })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /^Configure/ })).toHaveLength(1)
    expect(screen.getByText(/Used by alpha/)).toBeInTheDocument()
    expect(screen.getByText("No account needed")).toBeInTheDocument()
  })

  it("Configure: required key error, then saves the key and settings in the POST body only", async () => {
    const { calls } = mockApi(base(
      [svc({ account_settings: [{ name: "organisation", label: "Organisation", kind: "text", options: [], placeholder: "", help: "", value: "" }] })],
      { "POST /api/services/supabase/connect": { name: "supabase", connected: true, checked: "ok", message: "Supabase: connected, key checked OK." } },
    ))
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Connect Supabase" }))
    const dlg = await screen.findByRole("dialog")
    await userEvent.click(within(dlg).getByRole("button", { name: "Save and connect" }))
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("Paste SUPABASE_ACCESS_TOKEN to connect.")
    expect(calls.some((c) => c.path.endsWith("/connect"))).toBe(false)
    const box = within(dlg).getByLabelText("SUPABASE_ACCESS_TOKEN")
    expect(box).toHaveAttribute("type", "password")
    await userEvent.type(box, "sbp_secret")
    await userEvent.type(within(dlg).getByLabelText("Organisation"), "acme")
    await userEvent.click(within(dlg).getByRole("button", { name: "Save and connect" }))
    await waitFor(() => expect(calls.find((c) => c.path === "/api/services/supabase/connect")?.body)
      .toEqual({ values: { SUPABASE_ACCESS_TOKEN: "sbp_secret" }, settings: { organisation: "acme" } }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(document.body.textContent).not.toContain("sbp_secret")
  })

  it("a saved secret shows only its last characters with Replace", async () => {
    mockApi(base([svc({ connected: true, ends_in: { SUPABASE_ACCESS_TOKEN: "…abcd" } })]))
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Configure Supabase" }))
    const dlg = await screen.findByRole("dialog")
    expect(within(dlg).getByText("…abcd")).toBeInTheDocument()
    expect(within(dlg).queryByLabelText("SUPABASE_ACCESS_TOKEN")).toBeNull()
    await userEvent.click(within(dlg).getByRole("button", { name: "Replace" }))
    expect(within(dlg).getByLabelText("SUPABASE_ACCESS_TOKEN")).toBeInTheDocument()
    expect(within(dlg).getByRole("button", { name: "Save" })).toBeInTheDocument()
  })

  it("Test connection posts the pasted key and shows the result", async () => {
    const { calls } = mockApi(base([svc({})], {
      "POST /api/services/supabase/test": { name: "supabase", ok: true, message: "Supabase: the key works." },
    }))
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Connect Supabase" }))
    const dlg = await screen.findByRole("dialog")
    await userEvent.click(within(dlg).getByRole("button", { name: "Test connection" }))
    expect(await within(dlg).findByText("Paste the key first, then test.")).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText("SUPABASE_ACCESS_TOKEN"), "sbp_x")
    await userEvent.click(within(dlg).getByRole("button", { name: "Test connection" }))
    expect(await within(dlg).findByText("Supabase: the key works.")).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith("/test"))?.body).toEqual({ values: { SUPABASE_ACCESS_TOKEN: "sbp_x" } })
  })

  it("Disconnect asks first and names projects in use", async () => {
    const { calls } = mockApi(base([svc({ connected: true, used_by: ["alpha", "beta"] })], {
      "POST /api/services/supabase/disconnect": { name: "supabase", connected: false, used_by: [], warning: "" },
    }))
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Supabase" }))
    expect(await screen.findByText(/These projects use it: alpha, beta/)).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Disconnect" }))
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/disconnect"))?.body).toEqual({ yes: true }))
  })

  it("Models tab (from ?tab=) saves the grid", async () => {
    const models = {
      planner: { model: "claude-sonnet-5-5", fallback_models: ["claude-opus-5-5"], title: "Planner" },
      builder: { model: "claude-opus-5-5", fallback_models: [], title: "Builder" },
    }
    const { calls } = mockApi(base([], {
      "GET /api/global": { ...globalView, default_models: models },
      "POST /api/global/models": { saved: ["planner", "builder"] },
    }))
    renderWithProviders(<GlobalSettingsPage />, { route: "/settings?tab=models" })
    const planner = await screen.findByLabelText("Planner model 1")
    expect(screen.getByLabelText("Planner model 2")).toHaveValue("claude-opus-5-5")
    expect(screen.getByRole("button", { name: "Save models" })).toBeDisabled()
    await userEvent.selectOptions(planner, "claude-fable-5-1")
    await userEvent.selectOptions(screen.getByLabelText("Builder model 2"), "claude-sonnet-5-5")
    await userEvent.click(screen.getByRole("button", { name: "Save models" }))
    await waitFor(() => expect(calls.find((c) => c.path === "/api/global/models")?.body).toEqual({
      steps: {
        planner: { model: "claude-fable-5-1", fallback_models: ["claude-opus-5-5"] },
        builder: { model: "claude-opus-5-5", fallback_models: ["claude-sonnet-5-5"] },
      },
    }))
  })

  it("Updates tab shows the pill, the panel and the history", async () => {
    const supported = { ...info, update: { supported: true, installed: "v9.1", newest: "v9.2", available: true, can_install: true, reason: "", endpoints: { install: "update/install", rollback: "update/rollback" } } }
    mockApi(base([], {
      "GET /api/info": supported,
      "GET /api/update": {
        supported: true, installed: { tag: "v9.1", commit: "a" }, previous: { tag: "v9.0", commit: "b" }, newest: "v9.2",
        update_available: true, can_rollback: true, busy: false, busy_reason: "", running: false, waiting: "", phase: null,
        interrupted: false, last: null, log_tail: [],
      },
      "GET /api/update/history": { history: [{ at: "2026-10-31T10:00:00+00:00", action: "install", tag: "v9.1", result: "installed", reason: "", who: "dashboard" }] },
    }))
    renderWithProviders(<GlobalSettingsPage />, { route: "/settings?tab=updates" })
    expect(await screen.findByRole("button", { name: "Install update v9.2" })).toBeEnabled()
    expect(screen.getByRole("button", { name: /Updates/ })).toHaveTextContent("v9.2")
    expect(await screen.findByText("2026-10-31")).toBeInTheDocument()
  })

  it("Dashboard addresses: edit and save the three addresses", async () => {
    const { calls } = mockApi(base([], { "POST /api/global/addresses": { values: {}, api_restart: "asked" } }), )
    renderWithProviders(<GlobalSettingsPage />, { route: "/settings?tab=addresses" })
    expect(await screen.findByRole("heading", { name: "Dashboard addresses" })).toBeInTheDocument()
    const save = screen.getByRole("button", { name: "Save addresses" })
    expect(save).toBeDisabled()
    expect(screen.getByLabelText("Dashboard address")).toHaveValue("https://phoenix.example.test/")
    await userEvent.type(screen.getByLabelText("VS Code address"), "https://code.example.test/")
    await userEvent.type(screen.getByLabelText("Allowed page addresses"), "\nhttps://other.example.test")
    await userEvent.click(save)
    await waitFor(() => expect(calls.some((c) => c.path === "/api/global/addresses")).toBe(true))
    expect(calls.find((c) => c.path === "/api/global/addresses")!.body).toEqual({
      dashboard_url: "https://phoenix.example.test/",
      allowed_origins: ["https://phoenix.example.test", "https://other.example.test"],
      vscode_url: "https://code.example.test/",
    })
  })

  it("Dashboard addresses: an empty allowed list cannot be saved", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />, { route: "/settings?tab=addresses" })
    await userEvent.clear(await screen.findByLabelText("Allowed page addresses"))
    expect(screen.getByRole("button", { name: "Save addresses" })).toBeDisabled()
    expect(screen.getByRole("alert")).toHaveTextContent("Keep at least one allowed page address.")
  })
})
