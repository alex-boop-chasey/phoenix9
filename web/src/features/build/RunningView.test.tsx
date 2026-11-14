import { act, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useLocation } from "react-router"

import { BUILDS, build, line, openGate, runDetail } from "@/test/buildFixtures"
import { failure, mockApi } from "@/test/mockApi"
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
  "GET /api/runs/demo-site/estimates": { project: "demo-site", steps: {} },
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
  // no number in the ring any more (O41): the task count is a text line in the card
  expect(within(aside).getByTestId("sum-ring")).not.toHaveTextContent(/\d/)
  expect(within(aside).getByTestId("task-count")).toHaveTextContent("Tasks 1 of 3 done")
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

test("a failed build whose tasks all passed names the step it failed at", async () => {
  const d = runDetail({ status: "failed", gates: [] })
  const tasks = Object.fromEntries(Object.entries(d.tasks).map(([n, t]) => [n, { ...t, status: "passed" as const, gate: null }]))
  const failedAt = { step: "full-suite", title: "Full suite", reason: "2 tests failed", text: "Failed at: Full suite: 2 tests failed" }
  mockApi(routes({ [`GET ${RUN}`]: { ...d, tasks, failed_at: failedAt, error: "Full suite failed: 2 tests failed" } }))
  show()
  expect(await screen.findByTestId("result")).toHaveTextContent("Result: Failed at: Full suite: 2 tests failed")
  expect(screen.getByText("Failed at: Full suite").closest("[data-status]")).toHaveAttribute(
    "title", "Failed at: Full suite: 2 tests failed")
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

test("a failed build offers Discard work, which confirms then posts discard", async () => {
  const failed = runDetail({ status: "failed", gates: [] })
  const { calls } = mockApi(routes({
    [`GET ${RUN}`]: failed,
    [`POST ${RUN}/discard`]: { run_id: "r-wait", status: "failed", discarded: true, notes: [] },
  }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  await userEvent.click(screen.getByRole("button", { name: "Discard work" }))
  expect(calls.some((c) => c.path.endsWith("/discard"))).toBe(false)
  const dialog = await screen.findByRole("alertdialog")
  await userEvent.click(within(dialog).getByRole("button", { name: "Discard work" }))
  await waitFor(() => expect(calls.some((c) => c.path === `${RUN}/discard`)).toBe(true))
  expect(calls.find((c) => c.path === `${RUN}/discard`)!.body).toEqual({ confirm: true })
})

test("discard that would lose work explains what and needs a second, clearly-labelled confirm", async () => {
  const failed = runDetail({ status: "failed", gates: [] })
  const lost = ["its branch has 2 commits that main doesn't have"]
  const { calls } = mockApi(routes({
    [`GET ${RUN}`]: failed,
    [`POST ${RUN}/discard`]: (req: { body: unknown }) => (req.body as { force?: boolean }).force
      ? { run_id: "r-wait", status: "failed", discarded: true, notes: [] }
      : failure(409, "Run r-wait still has work that would be lost.", { needs_force: true, would_lose: lost }),
  }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  await userEvent.click(screen.getByRole("button", { name: "Discard work" }))
  const first = await screen.findByRole("alertdialog")
  expect(first).toHaveTextContent(/open merge request|not on main/)
  await userEvent.click(within(first).getByRole("button", { name: "Discard work" }))
  const second = await screen.findByRole("alertdialog", { name: "This build has work that isn't on main" })
  expect(second).toHaveTextContent("its branch has 2 commits that main doesn't have")
  const posts = () => calls.filter((c) => c.path === `${RUN}/discard`)
  expect(posts()).toHaveLength(1)
  expect(posts()[0]!.body).toEqual({ confirm: true })
  await userEvent.click(within(second).getByRole("button", { name: "Discard anyway and lose this work" }))
  await waitFor(() => expect(posts()).toHaveLength(2))
  expect(posts()[1]!.body).toEqual({ confirm: true, force: true })
})

test("a discarded build says work discarded and has no Discard button", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "stopped", gates: [], discarded: true }) }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  expect(screen.getByTestId("discarded")).toHaveTextContent("Work discarded")
  expect(screen.queryByRole("button", { name: "Discard work" })).toBeNull()
})

test("a running build has no Discard button", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ status: "running", gates: [] }) }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  expect(screen.queryByRole("button", { name: "Discard work" })).toBeNull()
})

test("the run's exact image id shows small in the header", async () => {
  mockApi(routes({ [`GET ${RUN}`]: runDetail({ image: { tag: "phoenix9-step-web:1", id: "sha256:0123456789abcdef" } }) }))
  show()
  await screen.findByRole("heading", { name: "Pricing page" })
  const id = screen.getByTestId("image-id")
  expect(id).toHaveTextContent("0123456789ab")
  expect(id).toHaveAttribute("title", "phoenix9-step-web:1 sha256:0123456789abcdef")
})

describe("progress ring and clocks (O41)", () => {
  const ago = (secs: number) => new Date(Date.now() - secs * 1000).toISOString()
  const ESTIMATES = {
    project: "demo-site",
    steps: {
      planner: { seconds: 120, samples: 5, source: "project" },
      builder: { seconds: 300, samples: 5, source: "project", per_task: true },
      summary: { seconds: 60, samples: 5, source: "project" },
    },
    task: { seconds: 600, samples: 5, source: "project" },
  }
  const planning = () => runDetail({
    status: "running", tasks: {}, gates: [],
    current: { group: "run-start", task: null, step: "planner", attempt: 1 },
    steps: [line({ group: "run-start", task: null, step: "planner", status: "running", started: ago(30), finished: "" })],
  })
  const building = (secs: number) => runDetail({
    status: "running", gates: [],
    current: { group: "task", task: 2, step: "builder", attempt: 1 },
    tasks: {
      "1": { title: "Pricing table", status: "passed", tries: 1, failures: [], depends_on: [] },
      "2": { title: "Plan cards", status: "running", tries: 1, failures: [], depends_on: [1] },
      "3": { title: "Footer", status: "pending", tries: 0, failures: [], depends_on: [2] },
    } as never,
    steps: [
      line({ group: "run-start", task: null, step: "planner" }),
      line({ task: 1 }), line({ task: 1, step: "check" }),
      line({ task: 2, status: "running", started: ago(secs), finished: "" }),
    ],
  })
  const aside = async () => {
    await screen.findByRole("heading", { name: "Pricing page" })
    return screen.getByRole("complementary", { name: "Build summary" })
  }

  test("while the Planner works there is no 0/0 and, without history, a calm moving ring", async () => {
    mockApi(routes({ [`GET ${RUN}`]: planning() }))
    show()
    const a = await aside()
    expect(a).not.toHaveTextContent("0/0")
    const ring = within(a).getByTestId("sum-ring")
    expect(ring).toHaveClass("calm")
    expect(ring).toHaveAttribute("data-fill", "calm")
    expect(within(a).queryByTestId("step-to-go")).toBeNull()
    expect(within(a).queryByTestId("task-count")).toBeNull()
  })

  test("with history the ring follows the current step and says about how long is left", async () => {
    mockApi(routes({ [`GET ${RUN}`]: building(60), "GET /api/runs/demo-site/estimates": ESTIMATES }))
    show()
    const a = await aside()
    expect(await within(a).findByTestId("step-to-go")).toHaveTextContent("about 4 min to go")
    const ring = within(a).getByTestId("sum-ring")
    expect(ring).not.toHaveClass("calm")
    expect(Number(ring.getAttribute("data-fill"))).toBeCloseTo(0.2, 1)
    // tasks 2 (10 min less 1 min) and 3 (10 min) + summary (1 min) = 20 min
    expect(within(a).getByTestId("build-to-go")).toHaveTextContent("Whole build: about 20 min to go")
    expect(within(a).getByTestId("task-count")).toHaveTextContent("Tasks 1 of 3 done")
  })

  test("past the estimate it says so and the ring holds short of full", async () => {
    mockApi(routes({ [`GET ${RUN}`]: building(900), "GET /api/runs/demo-site/estimates": ESTIMATES }))
    show()
    const a = await aside()
    expect(await within(a).findByTestId("step-to-go")).toHaveTextContent("taking longer than usual")
    expect(Number(within(a).getByTestId("sum-ring").getAttribute("data-fill"))).toBeLessThan(0.95)
  })

  test("\"This step\" and the step tile tell the same time; the build time is \"Build running\"", async () => {
    mockApi(routes({ [`GET ${RUN}`]: building(300) }))
    show()
    const a = await aside()
    expect(within(a).getByText("Build running")).toBeInTheDocument()
    expect(within(a).queryByText("Duration")).toBeNull()
    const clock = within(a).getByTestId("this-step").textContent!
    expect(clock).toBe("Started 5 minutes ago")
    expect(stepRow(2, "builder")).toHaveTextContent(clock)
  })
})
