import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { line, openGate, runDetail } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { StepList } from "./StepList"

afterEach(() => vi.unstubAllGlobals())

const show = (run = runDetail(), props = {}) => {
  mockApi({})
  return renderWithProviders(<StepList run={run} {...props} />)
}
const blocks = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)
const stepRow = (block: string, step: string) =>
  within(screen.getByRole("heading", { name: new RegExp(block) }).closest("section")!)
    .getAllByText(step)[0]!.closest("[data-step]") as HTMLElement

test("run-level steps once at top and bottom", () => {
  show()
  expect(blocks()[0]).toBe("At the start")
  expect(blocks().at(-1)).toBe("At the end")
  expect(screen.getAllByText("Planner")).toHaveLength(1)
  expect(screen.getAllByText("Summary")).toHaveLength(1)
})

test("task block repeated per task in order", () => {
  show()
  expect(blocks()).toEqual(["At the start", "Task 1: Pricing table", "Task 2: Plan cards", "Task 3: Footer", "At the end"])
  expect(screen.getAllByText("Builder")).toHaveLength(3)
  expect(screen.getByText("attempt 2 of 3")).toBeInTheDocument()
})

test("badge per step status incl spinner and waiting", () => {
  const run = runDetail({
    steps: [
      line({ group: "run-start", task: null, step: "planner", status: "passed" }),
      line({ task: 1, status: "running", finished: "" }),
      line({ task: 1, step: "check", status: "waiting" }),
      line({ task: 2, status: "failed" }),
    ],
    gates: [],
  })
  show(run)
  expect(within(stepRow("Task 1", "Builder")).getByTestId("spinner")).toBeInTheDocument()
  expect(stepRow("Task 1", "Check").querySelector('[data-status="waiting"]')).toHaveTextContent("Waiting for you")
  expect(stepRow("Task 2", "Builder").querySelector('[data-status="failed"]')).not.toBeNull()
  expect(stepRow("At the start", "Planner").querySelector('[data-status="passed"]')).not.toBeNull()
  expect(stepRow("Task 2", "Check").querySelector('[data-status="pending"]')).not.toBeNull()
})

test("skipped shows reason", () => {
  show()
  const row = stepRow("Task 3", "Builder")
  expect(row.querySelector('[data-status="skipped"]')).not.toBeNull()
  expect(row).toHaveTextContent("depends on task 2, which failed")
  const off = stepRow("Task 1", "Review")
  expect(off.querySelector('[data-status="skipped"]')).not.toBeNull()
  expect(off).toHaveTextContent("switched off")
})

test("escalation card under its failed step", () => {
  mockApi({})
  renderWithProviders(<StepList run={runDetail()} gates={[openGate]} />)
  const row = stepRow("Task 2", "Builder")
  expect(within(row).getByText(openGate.title)).toBeInTheDocument()
  expect(screen.getAllByText(openGate.title)).toHaveLength(1)
  expect(row).toHaveTextContent("the checks failed")
})

test("long note truncated", async () => {
  const note = "x".repeat(300)
  show(runDetail({ steps: [line({ task: 1, status: "failed", note })], gates: [] }))
  const shown = stepRow("Task 1", "Builder").querySelector(".truncate")!
  expect(shown.textContent!.length).toBeLessThan(150)
  await userEvent.hover(shown)
  expect((await screen.findAllByText(note)).length).toBeGreaterThan(0)
})

test("unfrozen plan says planned", () => {
  show(runDetail({ plan_frozen: false }))
  expect(screen.getByText("Planned steps; the runner fixes them when the build starts.")).toBeInTheDocument()
})
