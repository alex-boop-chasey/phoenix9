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

  it("services unsupported shows planned list not connected", async () => {
    mockApi(base())
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("Connecting services comes in a later update.")).toBeInTheDocument()
    expect(screen.getByText("Supabase")).toBeInTheDocument()
    expect(screen.getByText("OpenRouter")).toBeInTheDocument()
  })

  it("services supported shows rows with keys form", async () => {
    mockApi(base({
      "GET /api/services": {
        supported: true,
        services: [{ name: "resend", title: "Resend", connected: true }, { name: "mux", title: "Mux", connected: false }],
      },
      "GET /api/projects/resend/keys": [],
    }))
    const { default: userEvent } = await import("@testing-library/user-event")
    renderWithProviders(<GlobalSettingsPage />)
    expect(await screen.findByText("Resend")).toBeInTheDocument()
    expect(screen.getByText("Mux")).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "Keys" })[0]!)
    expect(await screen.findByRole("button", { name: /Save/ })).toBeInTheDocument()
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
