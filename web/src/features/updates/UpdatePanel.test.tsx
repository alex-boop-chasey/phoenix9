import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { UpdatePanel } from "@/features/updates/UpdatePanel"
import type { UpdateStatus } from "@/lib/types"
import { info } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const supportedInfo = {
  ...info,
  update: {
    supported: true, installed: "v9.1", newest: "v9.2", available: true, can_install: true, reason: "",
    endpoints: { install: "update/install", rollback: "update/rollback" },
  },
}

const status = (over: Partial<UpdateStatus> = {}): UpdateStatus => ({
  supported: true, installed: { tag: "v9.1", commit: "a" }, previous: { tag: "v9.0", commit: "b" }, newest: "v9.2",
  update_available: true, can_rollback: true, busy: false, busy_reason: "", running: false, waiting: "", phase: null,
  interrupted: false, last: null, log_tail: ["asked for install v9.2"], ...over,
})

describe("UpdatePanel", () => {
  it("shows versions and enables Install only when newer and idle", async () => {
    mockApi({ "GET /api/info": supportedInfo, "GET /api/update": status() })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Install update v9.2" })).toBeEnabled()
    expect(screen.getByText("v9.1")).toBeInTheDocument()
    expect(screen.getByText("Previous")).toBeInTheDocument()
    expect(screen.getByText("Newest")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Roll back to v9.0" })).toBeEnabled()
  })

  it("Install is disabled when nothing is newer", async () => {
    mockApi({ "GET /api/info": supportedInfo, "GET /api/update": status({ update_available: false }) })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Install update v9.2" })).toBeDisabled()
    expect(screen.getByText("Phoenix is up to date")).toBeInTheDocument()
  })

  it("disabled reason when busy", async () => {
    mockApi({ "GET /api/info": supportedInfo, "GET /api/update": status({ busy: true, busy_reason: "A build is mid-task" }) })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Install update v9.2" })).toBeDisabled()
    expect(screen.getByText("A build is mid-task")).toBeInTheDocument()
  })

  it("Rollback disabled without previous", async () => {
    mockApi({
      "GET /api/info": supportedInfo,
      "GET /api/update": status({ previous: null, can_rollback: false }),
    })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByRole("button", { name: "Roll back" })).toBeDisabled()
  })

  it("Install confirm then waiting state survives failed polls", async () => {
    let step = 0
    const { calls } = mockApi({
      "GET /api/info": supportedInfo,
      "GET /api/update": () => {
        step += 1
        if (step === 1) return status()                                   // the first load
        if (step === 2) return status({ running: true, waiting: "Waiting for task 3 of run X to finish" })
        if (step === 3) throw new Error("API restarting")                  // failed poll
        return status({ installed: { tag: "v9.2", commit: "c" }, previous: { tag: "v9.1", commit: "a" },
          last: { action: "install", tag: "v9.2", result: "installed", reason: "", at: "t1" } })
      },
      "POST /api/update/install": { ok: true, queued: true },
    })
    renderWithProviders(<UpdatePanel />)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(await screen.findByRole("button", { name: "Install update v9.2" }))
    expect(calls.some((c) => c.path === "/api/update/install")).toBe(false)
    expect(screen.getByText(/the dashboard is away for a few seconds/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Install" }))
    await waitFor(() => expect(calls.some((c) => c.path === "/api/update/install")).toBe(true))
    expect(calls.find((c) => c.path === "/api/update/install")?.body).toEqual({ yes: true, tag: "v9.2" })
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(await screen.findByText(/Waiting for task 3 of run X to finish/)).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(await screen.findByText("Restarting…")).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(await screen.findByText("Now v9.2")).toBeInTheDocument()
  })

  it("unsupported shows installed version only", async () => {
    mockApi({ "GET /api/info": info })
    renderWithProviders(<UpdatePanel />)
    expect(await screen.findByText(/Installed: v0.9.0. Installing updates from the dashboard comes in a later update./)).toBeInTheDocument()
    expect(screen.queryByRole("button")).toBeNull()
  })
})
