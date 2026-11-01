import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { DeployCard } from "@/features/deploy/DeployCard"
import type { DeployStatus } from "@/lib/types"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const deploys = (over: Partial<DeployStatus> = {}, supported = true, name = "vps-docker"): DeployStatus => ({
  project: "demo", deployer: { name, title: "VPS Docker", supported }, live_url: "https://demo.example",
  last_good_commit: "abcdef1234", last_good_at: "2026-10-01T10:00:00Z",
  recent: [{ at: "2026-10-01T10:00:00Z", commit: "abcdef1234", version: "v1", url: "https://demo.example", ok: true,
    rolled_back: false, reason: "", who: "alex", deployer: name }], ...over,
})

describe("DeployCard", () => {
  it("hidden for none, says not supported for stubs", async () => {
    mockApi({ "GET /api/projects/none-one/deploys": deploys({}, true, "none") })
    const { container } = renderWithProviders(<DeployCard name="none-one" />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
    vi.unstubAllGlobals()
    mockApi({ "GET /api/projects/stubby/deploys": deploys({}, false, "vercel") })
    renderWithProviders(<DeployCard name="stubby" />)
    expect(await screen.findByText("VPS Docker is not yet supported.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Deploy now" })).toBeNull()
  })

  it("deploy now shows progress then result", async () => {
    let polls = 0
    const { calls } = mockApi({
      "GET /api/projects/demo/deploys": deploys(),
      "POST /api/projects/demo/deploy": { job: "abc123" },
      "GET /api/jobs/abc123": () => {
        polls += 1
        return polls < 2
          ? { id: "abc123", kind: "deploy", project: "demo", status: "running", steps: [], message: "" }
          : { id: "abc123", kind: "deploy", project: "demo", status: "done", steps: [], message: "",
              result: { ok: true, url: "https://demo.example" } }
      },
    })
    renderWithProviders(<DeployCard name="demo" />)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    expect(await screen.findByRole("link", { name: "https://demo.example" })).toBeInTheDocument()
    expect(screen.getByText(/abcdef1 · ok/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Deploy now" }))
    await user.click(screen.getAllByRole("button", { name: "Deploy now" }).at(-1)!)
    await waitFor(() => expect(calls.some((c) => c.path === "/api/projects/demo/deploy")).toBe(true))
    expect(await screen.findByText("Deploying…")).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
    expect(await screen.findByText("Deployed to https://demo.example.")).toBeInTheDocument()
  })
})
