import { screen } from "@testing-library/react"

import { OverviewTab } from "@/features/overview/OverviewTab"
import { builds, gate, projects } from "@/test/fixtures"
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
    expect(await screen.findByText("Needs you: Task 2 needs you")).toBeInTheDocument()
    expect(screen.queryByText(/Other project gate/)).toBeNull()
    expect(screen.getByRole("button", { name: "Acknowledged" })).toBeInTheDocument()
  })

  it("current build line for a running run", async () => {
    mockApi(routes("tiny-tool", { "GET /api/gates": [] }))
    renderWithProviders(<OverviewTab name="tiny-tool" />)
    expect(await screen.findByText("Running task 2 of 4")).toBeInTheDocument()
    expect(screen.getByText("Running")).toBeInTheDocument()
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

  it("empty states", async () => {
    mockApi(routes("notes-only", { "GET /api/gates": [] }))
    renderWithProviders(<OverviewTab name="notes-only" />)
    expect(await screen.findByText("No build running.")).toBeInTheDocument()
    expect(await screen.findByText("No changes recorded yet.")).toBeInTheDocument()
    expect(screen.queryByText(/Needs you/)).toBeNull()
  })
})
