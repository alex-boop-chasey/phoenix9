import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { BUILDS, openGate, runDetail } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { BuildTab } from "./BuildTab"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const routes = (over: Record<string, unknown> = {}) => ({
  "GET /api/projects/demo-site/runs": BUILDS,
  "GET /api/runs/demo-site/r-wait": runDetail(),
  "GET /api/events/recent": { events: [], next: 0 },
  ...over,
})
const show = (route = "/p/demo-site/build") => renderWithProviders(<BuildTab name="demo-site" />, { route })

test("start new build opens the wizard", async () => {
  mockApi(routes({
    "GET /api/projects/demo-site/settings": { project: "demo-site", values: {}, source: {} },
    "GET /api/library/presets": { presets: [] },
    "GET /api/library/steps": { steps: [], problems: [] },
    "GET /api/projects/demo-site/specs": [],
    "POST /api/projects/demo-site/plan": { groups: {}, steps: [], errors: [], settings: {} },
  }))
  show("/p/demo-site/build?list=1")
  await userEvent.click(screen.getByRole("button", { name: "Start new build" }))
  expect(await screen.findByText("Step 1 of 7")).toBeInTheDocument()
})

test("run detail links to its logs", async () => {
  mockApi(routes())
  show("/p/demo-site/build?run=r-wait")
  const link = await screen.findByRole("link", { name: "See this build's logs" })
  expect(link).toHaveAttribute("href", "/p/demo-site/logs?run=r-wait")
  expect(screen.getByRole("link", { name: "← All builds" })).toHaveAttribute("href", "/p/demo-site/build?list=1")
})

test("run detail shows open gates", async () => {
  mockApi(routes({
    "GET /api/runs/demo-site/r-wait": runDetail({
      gates: [openGate, { ...openGate, id: "r-wait.2", kind: "merge", title: "Merge it?", task: null, step: null }],
    }),
  }))
  show("/p/demo-site/build?run=r-wait")
  expect(await screen.findByText("Merge it?")).toBeInTheDocument()
  expect(screen.getAllByText(openGate.title)).toHaveLength(1)
})

test("polls while running and stops when done", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let n = 0
  const { calls } = mockApi(routes({
    "GET /api/runs/demo-site/r-wait": () => (++n < 3 ? runDetail({ status: "running" }) : runDetail({ status: "done" })),
  }))
  show("/p/demo-site/build?run=r-wait")
  const runCalls = () => calls.filter((c) => c.path === "/api/runs/demo-site/r-wait").length
  await waitFor(() => expect(runCalls()).toBe(1))
  await act(() => vi.advanceTimersByTimeAsync(4100))
  await waitFor(() => expect(runCalls()).toBe(2))
  await act(() => vi.advanceTimersByTimeAsync(4100))
  await waitFor(() => expect(runCalls()).toBe(3))
  await act(() => vi.advanceTimersByTimeAsync(20000))
  expect(runCalls()).toBe(3)
})
