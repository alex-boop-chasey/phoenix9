import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { UpdatePanel } from "@/features/updates/UpdatePanel"
import { info } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const supported = (over: Record<string, unknown> = {}) => ({
  ...info,
  update: {
    supported: true, installed: "0.9.0", newest: "0.10.0", available: true, can_install: true, reason: "",
    endpoints: { install: "update/install", rollback: "update/rollback" }, ...over,
  },
})

describe("UpdatePanel", () => {
  it("unsupported shows installed version only", async () => {
    mockApi({ "GET /api/info": info })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByText(/Installed: v0.9.0. Installing updates from the dashboard comes in a later update./)).toBeInTheDocument()
    expect(screen.queryByRole("button")).toBeNull()
  })

  it("supported shows install and roll back", async () => {
    mockApi({ "GET /api/info": supported() })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Install update v0.10.0" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Roll back" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Last update log" })).toHaveAttribute("href", "/p/phoenix9/logs?kind=service")
  })

  it("install disabled with reason", async () => {
    mockApi({ "GET /api/info": supported({ can_install: false, reason: "A build is mid-task" }) })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Install update v0.10.0" })).toBeDisabled()
    expect(screen.getByText("A build is mid-task")).toBeInTheDocument()
  })

  it("roll back confirms", async () => {
    const { calls } = mockApi({ "GET /api/info": supported(), "POST /api/update/rollback": {} })
    renderWithProviders(<UpdatePanel />)
    await userEvent.click(await screen.findByRole("button", { name: "Roll back" }))
    expect(calls.some((c) => c.path === "/api/update/rollback")).toBe(false)
    await userEvent.click(screen.getAllByRole("button", { name: "Roll back" }).at(-1)!)
    await waitFor(() => expect(calls.some((c) => c.path === "/api/update/rollback")).toBe(true))
  })

  it("after install polls info until version changes", async () => {
    let version = "0.9.0"
    mockApi({
      "GET /api/info": () => {
        const i = supported({ installed: version })
        return { ...i, version }
      },
      "POST /api/update/install": {},
    })
    renderWithProviders(<UpdatePanel />)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(
      await screen.findByRole("button", { name: "Install update v0.10.0" }),
    )
    expect(await screen.findByText("Phoenix is restarting; this page reconnects by itself.")).toBeInTheDocument()
    version = "0.10.0"
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    await waitFor(() => expect(screen.queryByText(/Phoenix is restarting/)).toBeNull())
  })

  it("gives up after 3 minutes with a plain message", async () => {
    mockApi({ "GET /api/info": supported(), "POST /api/update/install": {} })
    renderWithProviders(<UpdatePanel />)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(
      await screen.findByRole("button", { name: "Install update v0.10.0" }),
    )
    await screen.findByText(/Phoenix is restarting/)
    await act(async () => { await vi.advanceTimersByTimeAsync(3 * 60 * 1000 + 2100) })
    expect(await screen.findByText(/did not come back after 3 minutes/)).toBeInTheDocument()
  })
})
