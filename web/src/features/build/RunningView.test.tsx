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
const headings = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)
const taskBox = (n: number) => document.querySelector(`[data-task="${n}"]`) as HTMLElement
const stepRow = (task: number | null, step: string) =>
  [...(task === null ? document.body : taskBox(task)).querySelectorAll(`[data-step=${step}]`)].at(-1) as HTMLElement

test("run-level steps once at top and bottom, task groups in between", async () => {
  mockApi(routes())
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  expect(headings()[0]).toBe("At the start")
  expect(headings().at(-1)).toBe("At the end")
  expect(screen.getAllByText("Planner")).toHaveLength(1)
  expect(screen.getAllByText("Summary")).toHaveLength(1)
  expect(taskBox(1)).toHaveTextContent("Task 1 · Pricing table")
  expect(taskBox(3)).toHaveTextContent("Task 3 · Footer")
})

test("summary aside shows the ring, badge, preset, cost and logs link", async () => {
  mockApi(routes())
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  const aside = screen.getByRole("complementary", { name: "Build summary" })
  expect(within(aside).getByTestId("ring-text")).toHaveTextContent("1/3")
  expect(within(aside).getByText("Waiting for you")).toBeInTheDocument()
  expect(within(aside).getByText("full")).toBeInTheDocument()
  expect(await within(aside).findByText("$0.80")).toBeInTheDocument()
  expect(within(aside).getByText("30 min")).toBeInTheDocument()
  // the ring has its own class, not the framework's "ring" box-shadow class
  const ring = aside.querySelector(".sum-ring")!
  expect(ring).not.toBeNull()
  expect(aside.querySelector(".ring")).toBeNull()
})

test("running build: blue ring text, spinner on the running block", async () => {
  mockApi(routes({
    [`GET ${RUN}`]: runDetail({
      status: "running",
      steps: [line({ task: 2, status: "running", finished: "" })],
      gates: [],
    }),
  }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  expect(stepRow(2, "builder").querySelector('[data-indicator="running"]')).not.toBeNull()
  const aside = screen.getByRole("complementary", { name: "Build summary" })
  expect(within(aside).getByText("Running task 2 of 3")).toBeInTheDocument()
  expect(within(aside).getByTestId("live-mode")).toBeInTheDocument()
})

test("escalation under failed step with Acknowledged posts acknowledged", async () => {
  const { calls } = mockApi(routes({
    [`POST /api/gates/${openGate.id}/answer`]: { gate: openGate.id, action: "acknowledged", note: "", who: "web", at: "" },
  }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  const row = stepRow(2, "builder")
  const buttons = within(row).getAllByRole("button").map((b) => b.textContent)
  expect(buttons[0]).toBe("Acknowledged")
  expect(buttons).toEqual(expect.arrayContaining(["Skip task", "Stop run"]))
  expect(screen.getAllByText(openGate.title)).toHaveLength(1)
  await userEvent.click(within(row).getByRole("button", { name: "Acknowledged" }))
  await waitFor(() => expect(calls.some((c) => c.path === `/api/gates/${openGate.id}/answer`)).toBe(true))
  const answer = calls.find((c) => c.path === `/api/gates/${openGate.id}/answer`)!
  expect(answer.body).toEqual({ action: "acknowledged", note: "" })
})

test("stop confirms then posts stop with confirm", async () => {
  const { calls } = mockApi(routes({ [`POST ${RUN}/stop`]: { run_id: "r-wait", status: "stopped", containers_removed: 1 } }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  await userEvent.click(screen.getByRole("button", { name: "Stop build" }))
  expect(calls.some((c) => c.path.endsWith("/stop"))).toBe(false)
  const dialog = await screen.findByRole("alertdialog")
  await userEvent.click(within(dialog).getByRole("button", { name: "Stop build" }))
  await waitFor(() => expect(calls.some((c) => c.path === `${RUN}/stop`)).toBe(true))
  expect(calls.find((c) => c.path === `${RUN}/stop`)!.body).toEqual({ confirm: true })
})

test("a stop the runner has not acted on yet says so", async () => {
  mockApi(routes({ [`POST ${RUN}/stop`]: { run_id: "r-wait", status: "stop requested", containers_removed: 0 } }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  await userEvent.click(screen.getByRole("button", { name: "Stop build" }))
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stop build" }))
  expect(await screen.findByText(/Stop requested/)).toBeInTheDocument()
})

test("sse event refetches the run", async () => {
  vi.stubGlobal("EventSource", FakeEventSource)
  const { calls } = mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "running", gates: [] }) }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
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
  await screen.findByRole("heading", { name: "Pricing page" })
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
  expect(await screen.findByText(/Starting… the first step runs/)).toBeInTheDocument()
  expect(screen.getByText("Planned steps; the runner fixes them when the build starts.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Stop build" })).toBeInTheDocument()
})

test("finished shows result and logs link", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "failed", gates: [] }) }))
  show()
  expect(await screen.findByTestId("result")).toHaveTextContent("Result: 1 of 3 tasks failed")
  expect(screen.getByRole("link", { name: "See this build's logs" })).toHaveAttribute("href", "/p/demo-site/logs?run=r-wait")
  expect(screen.queryByRole("button", { name: "Stop build" })).toBeNull()
  expect(screen.queryByTestId("live-mode")).toBeNull()
})

test("build tab opens on the running view when a run is active", async () => {
  mockApi(routes())
  show("/p/demo-site/build")
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/build?run=r-wait"))
  expect(await screen.findByRole("button", { name: "Stop build" })).toBeInTheDocument()
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
  await screen.findByRole("heading", { name: "Pricing page" })
  const aside = screen.getByRole("complementary", { name: "Build summary" })
  expect(await within(aside).findByText("30 min")).toBeInTheDocument()
  expect(within(aside).getByText("$0.80")).toBeInTheDocument()
})

test("header shows the run's branch", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "running", gates: [] }) }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  expect(screen.getByText("phoenix/r-wait")).toBeInTheDocument()
})
