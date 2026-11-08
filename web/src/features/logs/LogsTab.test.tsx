import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { LogsTab } from "@/features/logs/LogsTab"
import type { LogEntry, LogText } from "@/lib/types"
import { builds } from "@/test/fixtures"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const RUN = "20261020-090000-contact-form"
const entry = (o: Partial<LogEntry>): LogEntry => ({
  id: "x", kind: "step", run: RUN, task: 1, attempt: 1, step: "builder", title: "Entry",
  size: 100, modified: "2026-10-20T09:05:00Z", ...o,
})
const ENTRIES: LogEntry[] = [
  entry({ id: "s1", kind: "session", title: "Builder session", task: 1, step: "builder" }),
  entry({ id: "c1", kind: "check", title: "Check output", task: 1, step: "check" }),
  entry({ id: "d1", kind: "diff", title: "Task 2 diff", task: 2, step: "diff" }),
  entry({ id: "g1", kind: "gate", title: "Gate note", task: 0, attempt: null, step: null }),
]
const TEXTS: Record<string, Partial<LogText>> = {
  s1: { text: "hello from the builder" },
  d1: { text: "diff --git a/a b/a\n@@ -1 +1 @@\n-old\n+new", is_diff: true },
  c1: { text: "x".repeat(10), truncated: true },
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "GET /api/projects/demo-site/runs": builds,
    "GET /api/logs": (r: MockRequest) =>
      ENTRIES.filter((e) =>
        (!r.query.task || String(e.task) === r.query.task) &&
        (!r.query.step || e.step === r.query.step) &&
        (!r.query.kind || e.kind === r.query.kind)),
    "GET /api/logs/read": (r: MockRequest) => {
      const e = ENTRIES.find((x) => x.id === r.query.id)!
      return { id: e.id, kind: e.kind, title: e.title, text: "", truncated: false, is_diff: false, ...TEXTS[e.id] }
    },
    "GET /api/events/recent": { events: [], next: 0 },
    ...over,
  }
}

async function pick(label: string, option: string) {
  await userEvent.selectOptions(screen.getByRole("combobox", { name: label }), option)
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = () => {}
})

describe("LogsTab", () => {
  it("lists entries for the project", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    expect(await screen.findByText("Builder session")).toBeInTheDocument()
    expect(screen.getByText("Check output")).toBeInTheDocument()
    expect(screen.getByText("Task 2 diff")).toBeInTheDocument()
    expect(screen.getByText("Gate note")).toBeInTheDocument()
  })

  it("run filter narrows entries and sets the url", async () => {
    const { calls } = mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    await screen.findByText("Builder session")
    await pick("Build", `2026-10-20 · Contact form · done`)
    await waitFor(() => expect(calls.some((c) => c.path === "/api/logs" && c.query.run === RUN)).toBe(true))
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument()
  })

  it("task step and kind filters", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    await screen.findByText("Builder session")
    await pick("Task", "Build level")
    expect(await screen.findByText("Gate note")).toBeInTheDocument()
    expect(screen.queryByText("Builder session")).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }))
    await pick("Step", "check")
    expect(await screen.findByText("Check output")).toBeInTheDocument()
    expect(screen.queryByText("Builder session")).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }))
    await userEvent.click(screen.getByRole("button", { name: "Code changes" }))
    await userEvent.click(screen.getByRole("button", { name: "Questions" }))
    expect(await screen.findByText("Gate note")).toBeInTheDocument()
    expect(screen.queryByText("Builder session")).toBeNull()
    expect(screen.getByText("Task 2 diff")).toBeInTheDocument()
  })

  it("deep link with run and kind preselects filters", async () => {
    const { calls } = mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />, { route: `/p/demo-site/logs?run=${RUN}&kind=diff` })
    expect(await screen.findByText("Task 2 diff")).toBeInTheDocument()
    expect(screen.queryByText("Builder session")).toBeNull()
    expect(screen.getByRole("button", { name: "Code changes" })).toHaveAttribute("aria-pressed", "true")
    expect(calls.some((c) => c.path === "/api/logs" && c.query.run === RUN && c.query.kind === "diff")).toBe(true)
  })

  it("marks the open entry selected and shows the kind tag", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    await userEvent.click(await screen.findByText("Builder session"))
    await screen.findByText("hello from the builder")
    expect(screen.getByRole("option", { name: /Builder session/ })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("option", { name: /Check output/ })).toHaveAttribute("aria-selected", "false")
  })

  it("shows a loading state while the log loads", async () => {
    mockApi(routes({ "GET /api/logs/read": () => new Promise(() => {}) }))
    renderWithProviders(<LogsTab name="demo-site" />, { route: "/p/demo-site/logs?id=s1" })
    expect(await screen.findByTestId("log-loading")).toHaveTextContent("Loading log…")
  })

  it("clicking an entry loads its text", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    await userEvent.click(await screen.findByText("Builder session"))
    expect(await screen.findByText("hello from the builder")).toBeInTheDocument()
  })

  it("renders a diff coloured", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />)
    await userEvent.click(await screen.findByText("Task 2 diff"))
    expect((await screen.findByText("+new")).className).toContain("bg-ok")
  })

  it("copy button copies full text", async () => {
    mockApi(routes())
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    renderWithProviders(<LogsTab name="demo-site" />, { route: "/p/demo-site/logs?id=s1" })
    await screen.findByText("hello from the builder")
    await userEvent.click(screen.getByRole("button", { name: "Copy" }))
    expect(writeText).toHaveBeenCalledWith("hello from the builder")
  })

  it("truncated note shown", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />, { route: "/p/demo-site/logs?id=c1" })
    expect(await screen.findByText("Showing the last 2 MB")).toBeInTheDocument()
  })

  it("empty filters message", async () => {
    mockApi(routes({ "GET /api/logs": [] }))
    renderWithProviders(<LogsTab name="demo-site" />)
    expect(await screen.findByText("No logs match these filters.")).toBeInTheDocument()
  })

  it("error state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ ok: false, message: "Logs are unavailable" }), { status: 500 })))
    renderWithProviders(<LogsTab name="demo-site" />)
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("Logs are unavailable")
  })

  it("address filters set the controls and the query", async () => {
    const { calls } = mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />, { route: `/p/demo-site/logs?run=${RUN}&step=check&task=1&kind=diff` })
    await waitFor(() => expect(calls.some((c) => c.path === "/api/logs" && c.query.run === RUN && c.query.step === "check" && c.query.task === "1" && c.query.kind === "diff")).toBe(true))
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument()
  })

  it("address log= opens that log", async () => {
    mockApi(routes())
    renderWithProviders(<LogsTab name="demo-site" />, { route: "/p/demo-site/logs?log=s1" })
    expect(await screen.findByText("hello from the builder")).toBeInTheDocument()
  })

  describe("repair documents", () => {
    const NOTE = `${RUN}/repairs/notes/1-fix.md`
    const REPORT = `${RUN}/repairs/report.md`
    const docs: LogEntry[] = [
      entry({ id: NOTE, kind: "repair-note", task: null, attempt: null, step: null, title: "repair note 1-fix" }),
      entry({ id: REPORT, kind: "repair-report", task: null, attempt: null, step: null, title: "run report" }),
    ]
    const withDocs = () => routes({
      "GET /api/logs": docs,
      "GET /api/logs/read": (r: MockRequest) => ({
        id: r.query.id, kind: r.query.id === NOTE ? "repair-note" : "repair-report", title: "t",
        text: r.query.id === NOTE ? "# Fix\n- skip task 2" : "# Run report\nAll fine", truncated: false, is_diff: false,
      }),
    })

    it("lists them with plain labels", async () => {
      mockApi(withDocs())
      renderWithProviders(<LogsTab name="demo-site" />)
      const note = await screen.findByRole("option", { name: /repair note 1-fix/ })
      expect(note).toHaveTextContent("Repair note")
      expect(screen.getByRole("option", { name: /run report/ })).toHaveTextContent("Run report")
    })

    it("opens a note as text from the address", async () => {
      mockApi(withDocs())
      renderWithProviders(<LogsTab name="demo-site" />, { route: `/p/demo-site/logs?log=${encodeURIComponent(NOTE)}` })
      expect(await screen.findByText(/skip task 2/)).toBeInTheDocument()
    })

    it("opens a report when picked", async () => {
      mockApi(withDocs())
      renderWithProviders(<LogsTab name="demo-site" />)
      await userEvent.click(await screen.findByRole("option", { name: /run report/ }))
      expect(await screen.findByText(/All fine/)).toBeInTheDocument()
    })
  })
})
