import { screen, waitFor } from "@testing-library/react"

import GlobalSettingsPage from "@/pages/GlobalSettingsPage"
import { globalView, info } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const base = (over: Record<string, unknown> = {}) => ({
  "GET /api/global": globalView,
  "GET /api/services": { supported: false, services: [] },
  "GET /api/info": info,
  ...over,
})

describe("GlobalSettingsPage", () => {
  it("github connected shows accounts", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("rebirth-wd")).toBeInTheDocument()
    expect(screen.getByText("alex-boop-chasey")).toBeInTheDocument()
    expect(screen.getByText("Connected")).toBeInTheDocument()
  })

  it("github not connected shows how to connect and no token form", async () => {
    mockApi(base({ "GET /api/global": { ...globalView, github: { connected: false, accounts: [] } } }))
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText(/ask the Phoenix chat to connect it/)).toBeInTheDocument()
    expect(screen.queryByLabelText("GitHub token")).toBeNull()
  })

  it("token form shown only when supported and never echoes", async () => {
    const { calls } = mockApi(base({
      "GET /api/global": {
        ...globalView, github: { connected: false, accounts: [] },
        supported: { ...globalView.supported, github_connect: true }, endpoints: { github_connect: "github/connect" },
      },
      "POST /api/github/connect": { connected: true },
    }))
    const { default: userEvent } = await import("@testing-library/user-event")
    renderWithProviders(<GlobalSettingsPage />)
    const box = await screen.findByLabelText("GitHub token")
    expect(box).toHaveAttribute("type", "password")
    await userEvent.type(box, "ghp_secret")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(calls.some((c) => c.path === "/api/github/connect")).toBe(true)
    expect(document.body.textContent).not.toContain("ghp_secret")
    expect((box as HTMLInputElement).value).toBe("")
  })

  it("services unsupported says so", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("Connecting services is not available yet.")).toBeInTheDocument()
  })

  it("default models listed", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("check-writer")).toBeInTheDocument()
    expect(screen.getByText(/then haiku/)).toBeInTheDocument()
    expect(screen.getByText(/Change these per project/)).toBeInTheDocument()
  })

  it("telegram status", async () => {
    mockApi(base({ "GET /api/global": { ...globalView, telegram: { connected: true } } }))
    renderWithProviders(<GlobalSettingsPage />)
    await screen.findByText("Telegram")
    await waitFor(() => expect(screen.getAllByText("Connected").length).toBe(2))
  })
})

const svc = (over: Record<string, unknown>) => ({
  name: "supabase", title: "Supabase", description: "Database.", support: "store-and-wire", connected: false,
  note: "", account_keys: ["SUPABASE_ACCESS_TOKEN"], checked: "not checked", checked_at: "", used_by: [],
  endpoints: { connect: "services/supabase/connect", disconnect: "services/supabase/disconnect" }, ...over,
})
const withServices = (rows: unknown[], extra: Record<string, unknown> = {}) =>
  base({ "GET /api/services": { supported: true, services: rows }, ...extra })

describe("ServicesSection", () => {
  it("ServicesSection renders connected and not-connected rows", async () => {
    mockApi(withServices([
      svc({ connected: true, checked: "ok", used_by: ["alpha"] }),
      svc({ name: "resend", title: "Resend", endpoints: { connect: "services/resend/connect" } }),
    ]))
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("Supabase")).toBeInTheDocument()
    expect(screen.getByText("Resend")).toBeInTheDocument()
    expect(screen.getByText("Last check: ok")).toBeInTheDocument()
    expect(screen.getByText("Used by: alpha")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument()
  })

  it("Connect form posts values and shows the result line", async () => {
    const { calls } = mockApi(withServices([svc({})], {
      "POST /api/services/supabase/connect": { name: "supabase", connected: true, checked: "ok", message: "Supabase: connected, key checked OK." },
    }))
    const { default: userEvent } = await import("@testing-library/user-event")
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }))
    const box = screen.getByLabelText("SUPABASE_ACCESS_TOKEN")
    expect(box).toHaveAttribute("type", "password")
    await userEvent.type(box, "sbp_secret")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(await screen.findByText("Supabase: connected, key checked OK.")).toBeInTheDocument()
    const post = calls.find((c) => c.path === "/api/services/supabase/connect")
    expect(post?.body).toEqual({ values: { SUPABASE_ACCESS_TOKEN: "sbp_secret" } })
    expect((box as HTMLInputElement).value).toBe("")
    expect(document.body.textContent).not.toContain("sbp_secret")
  })

  it("Disconnect confirm names projects in use", async () => {
    const { calls } = mockApi(withServices([svc({ connected: true, used_by: ["alpha", "beta"] })], {
      "POST /api/services/supabase/disconnect": { name: "supabase", connected: false, used_by: ["alpha", "beta"], warning: "" },
    }))
    const { default: userEvent } = await import("@testing-library/user-event")
    renderWithProviders(<GlobalSettingsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }))
    expect(await screen.findByText(/These projects use it: alpha, beta/)).toBeInTheDocument()
    const buttons = screen.getAllByRole("button", { name: "Disconnect" })
    await userEvent.click(buttons[buttons.length - 1]!)
    await waitFor(() => expect(calls.some((c) => c.path === "/api/services/supabase/disconnect")).toBe(true))
    expect(calls.find((c) => c.path === "/api/services/supabase/disconnect")?.body).toEqual({ yes: true })
  })

  it("keys-only services show no Connect button", async () => {
    mockApi(withServices([svc({ name: "stripe", title: "Stripe", support: "keys-only", connected: true, account_keys: [], endpoints: {} })]))
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("No account connection needed")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull()
  })
})
