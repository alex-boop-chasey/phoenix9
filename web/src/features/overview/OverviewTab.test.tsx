import { screen, within } from "@testing-library/react"

import { OverviewTab } from "@/features/overview/OverviewTab"
import { builds, gate, info, projects } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

function routes(name: string, over: Record<string, unknown> = {}) {
  return {
    [`GET /api/projects/${name}`]: projects.find((p) => p.name === name),
    "GET /api/gates": [gate, { ...gate, id: "other.1", project: "phoenix9", title: "Other project gate" }],
    [`GET /api/projects/${name}/runs`]: builds,
    [`GET /api/projects/${name}/changelog`]: [],
    "GET /api/events/recent": { events: [], next: 0 },
    ...over,
  }
}

describe("OverviewTab", () => {
  it("shows open gates for this project only", async () => {
    mockApi(routes("demo-site"))
    renderWithProviders(<OverviewTab name="demo-site" />)
    expect(await screen.findByText("Task 2 needs you")).toBeInTheDocument()
    expect(screen.queryByText(/Other project gate/)).toBeNull()
    expect(screen.getByRole("button", { name: "Acknowledged" })).toBeInTheDocument()
  })

  it("current build line for a running run", async () => {
    mockApi(routes("tiny-tool", { "GET /api/gates": [] }))
    renderWithProviders(<OverviewTab name="tiny-tool" />)
    expect(await screen.findByText("Now: working on task 2 of 4.")).toBeInTheDocument()
    expect(screen.getByText("Running")).toBeInTheDocument()
    expect(screen.getByLabelText("0 of 4 tasks done")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open the Build tab" })).toHaveAttribute("href", "/p/tiny-tool/build")
  })

  it("recent changes newest first", async () => {
    mockApi(routes("notes-only", {
      "GET /api/gates": [],
      "GET /api/projects/notes-only/changelog": [
        { date: "2026-10-01", who: "alex", text: "Older change" },
        { date: "2026-10-02", who: "builder", text: "Newer change" },
      ],
    }))
    renderWithProviders(<OverviewTab name="notes-only" />)
    const newer = await screen.findByText("Newer change")
    const older = screen.getByText("Older change")
    expect(newer.compareDocumentPosition(older) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("a project with no builds offers to start the first one", async () => {
    mockApi(routes("notes-only", { "GET /api/gates": [], "GET /api/projects/notes-only/runs": [] }))
    renderWithProviders(<OverviewTab name="notes-only" />)
    const link = await screen.findByRole("link", { name: "Start the first build" })
    expect(link).toHaveAttribute("href", "/p/notes-only/build?new=1")
  })

  it("empty states", async () => {
    mockApi(routes("notes-only", { "GET /api/gates": [] }))
    renderWithProviders(<OverviewTab name="notes-only" />)
    expect(await screen.findByText("No build running.")).toBeInTheDocument()
    expect(await screen.findByText("No changes recorded yet.")).toBeInTheDocument()
    expect(screen.queryByText(/Needs you/)).toBeNull()
  })

  it("has no updates panel, even for phoenix9", async () => {
    mockApi(routes("phoenix9", { "GET /api/gates": [], "GET /api/info": info }))
    renderWithProviders(<OverviewTab name="phoenix9" />)
    await screen.findByText("Current build")
    expect(screen.queryByText("Phoenix updates")).toBeNull()
  })

  it("waiting merge shows an orange bar piece and the Now line", async () => {
    const run = { run_id: "r1", status: "waiting", task: null, tasks: 2, carrying_on: false,
      why: "It is waiting for your answer.", now: "Now: the merge step is waiting for you." }
    const base = projects.find((p) => p.name === "demo-site")!
    mockApi(routes("demo-site", {
      "GET /api/gates": [],
      "GET /api/projects/demo-site": { ...base, run },
      "GET /api/projects/demo-site/runs": [{ ...builds[0], run_id: "r1", status: "waiting", tasks_total: 2, tasks_passed: 2,
        title: "Pricing page", cost: "$3.84", duration: "38 min", current: { step: "merge" } }],
    }))
    const { container } = renderWithProviders(<OverviewTab name="demo-site" />)
    expect(await screen.findByText("Pricing page")).toBeInTheDocument()
    expect(screen.getByText("2 of 2 tasks · $3.84 · 38 min")).toBeInTheDocument()
    expect(screen.getByText("Now: the merge step is waiting for you.")).toBeInTheDocument()
    expect(container.querySelectorAll(".tbar i.need")).toHaveLength(1)
  })

  it("a run whose runner stopped checking in says Worker not responding", async () => {
    const base = projects.find((p) => p.name === "tiny-tool")!
    const run = { ...base.run!, worker: "not responding" as const,
      why: "It says running, but Phoenix's runner has not checked in for over 2 minutes.",
      now: "Now: worker not responding. Phoenix's runner has not checked in for over 2 minutes." }
    mockApi(routes("tiny-tool", { "GET /api/gates": [], "GET /api/projects/tiny-tool": { ...base, run, worker: "not responding" } }))
    renderWithProviders(<OverviewTab name="tiny-tool" />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Worker not responding.")
  })

  it("About card shows what was chosen at setup", async () => {
    const base = projects.find((p) => p.name === "tiny-tool")!
    mockApi(routes("tiny-tool", {
      "GET /api/gates": [],
      "GET /api/projects/tiny-tool": { ...base, services: ["supabase"], setup: {
        kind: "python-script", source: "template", template: "cli", preset: "quick", merge: "ask", created: "2026-10-01" } },
    }))
    renderWithProviders(<OverviewTab name="tiny-tool" />)
    const setup = within(await screen.findByLabelText("Chosen at setup"))
    expect(setup.getByText("Template cli")).toBeInTheDocument()
    expect(setup.getByText("Ask me first")).toBeInTheDocument()
    expect(setup.getByText("Default build preset")).toBeInTheDocument()   // each build shows its own preset
    expect(setup.getByText("2026-10-01")).toBeInTheDocument()
    expect(setup.getByText("alex-boop-chasey")).toBeInTheDocument()
    expect(screen.getByText("supabase")).toBeInTheDocument()
    expect(within(screen.getByLabelText("On this server")).getByText("Off")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Change these in Settings" })).toHaveAttribute("href", "/p/tiny-tool/settings")
  })
})
