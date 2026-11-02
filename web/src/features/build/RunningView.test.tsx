import { act, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useLocation } from "react-router"

import { BUILDS, build, line, openGate, runDetail } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { BuildTab } from "./BuildTab"

class FakeEventSource {
  static last: FakeEventSource | null = null
  onopen: (() => void) | null = null
  onmessage: ((m: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  listeners: Record<string, ((m: MessageEvent) => void)[]> = {}
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(type: string, data: object, id: string) {
    const m = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id })
    this.listeners[type]?.forEach((f) => f(m))
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const RUN = "/api/runs/demo-site/r-wait"
const routes = (over: Record<string, unknown> = {}) => ({
  "GET /api/projects/demo-site/runs": BUILDS,
  [`GET ${RUN}`]: runDetail(),
  "GET /api/events/recent": { events: [], next: 0 },
  ...over,
})

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}
const show = (route = "/p/demo-site/build?run=r-wait") =>
  renderWithProviders(<><BuildTab name="demo-site" /><Where /></>, { route })
const blocks = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)
const stepRow = (block: string, step: string) =>
  within(screen.getByRole("heading", { name: new RegExp(block) }).closest("section")!)
    .getAllByText(step)[0]!.closest("[data-step]") as HTMLElement

test("run-level steps once at top and bottom, task block per task", async () => {
  mockApi(routes())
  show()
  await screen.findByText("Pricing page")
  expect(blocks()).toEqual(["At the start", "Task 1: Pricing table", "Task 2: Plan cards", "Task 3: Footer", "At the end"])
  expect(screen.getAllByText("Planner")).toHaveLength(1)
  expect(screen.getAllByText("Summary")).toHaveLength(1)
  expect(screen.getAllByText("Builder")).toHaveLength(3)
  expect(screen.getByText("Task 2 of 3")).toBeInTheDocument()
})

test("badges per status incl spinner", async () => {
  mockApi(routes({
    [`GET ${RUN}`]: runDetail({
      status: "running",
      steps: [
        line({ group: "run-start", task: null, step: "planner", status: "passed" }),
        line({ task: 1, status: "running", finished: "" }),
        line({ task: 1, step: "check", status: "waiting" }),
        line({ task: 2, status: "failed" }),
      ],
      gates: [],
    }),
  }))
  show()
  await screen.findByText("Pricing page")
  expect(within(stepRow("Task 1", "Builder")).getByTestId("spinner")).toBeInTheDocument()
  expect(stepRow("Task 1", "Check").querySelector('[data-status="waiting"]')).not.toBeNull()
  expect(stepRow("Task 2", "Builder").querySelector('[data-status="failed"]')).not.toBeNull()
  expect(stepRow("At the start", "Planner").querySelector('[data-status="passed"]')).not.toBeNull()
  expect(stepRow("Task 2", "Check").querySelector('[data-status="pending"]')).not.toBeNull()
  expect(stepRow("Task 3", "Builder").querySelector('[data-status="skipped"]')).not.toBeNull()
  expect(within(screen.getByTestId("run-status")).getByTestId("spinner")).toBeInTheDocument()
})

test("escalation under failed step with Acknowledged posts acknowledged", async () => {
  const { calls } = mockApi(routes({
    [`POST /api/gates/${openGate.id}/answer`]: { gate: openGate.id, action: "acknowledged", note: "", who: "web", at: "" },
  }))
  show()
  await screen.findByText("Pricing page")
  const row = stepRow("Task 2", "Builder")
  const buttons = within(row).getAllByRole("button").map((b) => b.textContent)
  expect(buttons[0]).toBe("Acknowledged")
  expect(buttons).toEqual(expect.arrayContaining(["Skip task", "Stop run"]))
  expect(screen.getAllByText(`Needs you: ${openGate.title}`)).toHaveLength(1)
  await userEvent.click(within(row).getByRole("button", { name: "Acknowledged" }))
  await waitFor(() => expect(calls.some((c) => c.path === `/api/gates/${openGate.id}/answer`)).toBe(true))
  const answer = calls.find((c) => c.path === `/api/gates/${openGate.id}/answer`)!
  expect(answer.body).toEqual({ action: "acknowledged", note: "" })
})

test("stop confirms then posts stop with confirm", async () => {
  const { calls } = mockApi(routes({ [`POST ${RUN}/stop`]: { run_id: "r-wait", status: "stopped", containers_removed: 1 } }))
  show()
  await screen.findByText("Pricing page")
  await userEvent.click(screen.getByRole("button", { name: "Stop" }))
  expect(calls.some((c) => c.path.endsWith("/stop"))).toBe(false)
  const dialog = await screen.findByRole("alertdialog")
  await userEvent.click(within(dialog).getByRole("button", { name: "Stop build" }))
  await waitFor(() => expect(calls.some((c) => c.path === `${RUN}/stop`)).toBe(true))
  expect(calls.find((c) => c.path === `${RUN}/stop`)!.body).toEqual({ confirm: true })
})

test("sse event refetches the run", async () => {
  vi.stubGlobal("EventSource", FakeEventSource)
  const { calls } = mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "running", gates: [] }) }))
  show()
  await screen.findByText("Pricing page")
  expect(screen.getByTestId("live-mode")).toHaveTextContent("Live")
  const runCalls = () => calls.filter((c) => c.path === RUN).length
  const before = runCalls()
  await act(async () => {
    FakeEventSource.last!.emit("run.step.started", { type: "run.step.started", project: "demo-site", run: "r-wait", task: 2, step: "builder", data: {} }, "9")
  })
  await waitFor(() => expect(runCalls()).toBe(before + 1))
  await act(async () => {
    FakeEventSource.last!.emit("run.step.started", { type: "run.step.started", project: "demo-site", run: "other", task: 1, step: "builder", data: {} }, "10")
  })
  expect(runCalls()).toBe(before + 1)
})

test("falls back to polling when the stream errors", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.stubGlobal("EventSource", FakeEventSource)
  const { calls } = mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "running", gates: [] }) }))
  show()
  await screen.findByText("Pricing page")
  const runCalls = () => calls.filter((c) => c.path === RUN).length
  await act(() => vi.advanceTimersByTimeAsync(8000))
  expect(runCalls()).toBe(1)
  await act(async () => {
    FakeEventSource.last!.onerror?.()
  })
  expect(screen.getByTestId("live-mode")).toHaveTextContent("Updating every few seconds")
  await act(() => vi.advanceTimersByTimeAsync(4100))
  await waitFor(() => expect(runCalls()).toBe(2))
  expect(calls.some((c) => c.path === "/api/events/recent")).toBe(true)
})

test("queued message", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "queued", steps: [], gates: [], plan_frozen: false, current: {} }) }))
  show()
  expect(await screen.findByText("Queued: waiting for the runner to pick it up.")).toBeInTheDocument()
  expect(screen.getByText("Planned steps; the runner fixes them when the build starts.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument()
})

test("finished shows result, logs link and back to builds", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "failed", gates: [] }) }))
  show()
  expect(await screen.findByText("Result: 1 of 3 tasks failed")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "See this build's logs" })).toHaveAttribute("href", "/p/demo-site/logs?run=r-wait")
  expect(screen.queryByRole("button", { name: "Stop" })).toBeNull()
  expect(screen.queryByTestId("live-mode")).toBeNull()
  await userEvent.click(screen.getByRole("link", { name: "Back to builds" }))
  expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/build?list=1")
  expect(await screen.findByRole("button", { name: "Start new build" })).toBeEnabled()
})

test("build tab opens on the running view when a run is active", async () => {
  mockApi(routes())
  show("/p/demo-site/build")
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/build?run=r-wait"))
  expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument()
})

test("no active run opens on the list", async () => {
  mockApi(routes({ "GET /api/projects/demo-site/runs": [build({ run_id: "r-old", title: "Contact form", status: "done" })] }))
  show("/p/demo-site/build")
  expect(await screen.findByText("Contact form")).toBeInTheDocument()
  expect(screen.getByTestId("where")).toHaveTextContent(/\/build$/)
})

test("header shows duration and cost from the builds list", async () => {
  mockApi(routes())
  show()
  await screen.findByText("Pricing page")
  expect(await screen.findByText("Duration: 30 min")).toBeInTheDocument()
  expect(screen.getByText("Cost: $0.80")).toBeInTheDocument()
})
