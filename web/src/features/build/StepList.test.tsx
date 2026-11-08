import { screen, within } from "@testing-library/react"

import { line, openGate, runDetail } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { StepList, gatesShownInSteps } from "./StepList"

afterEach(() => vi.unstubAllGlobals())

const show = (run = runDetail(), props = {}) => {
  mockApi({})
  return renderWithProviders(<StepList run={run} {...props} />)
}
const headings = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)
const taskBox = (n: number) => document.querySelector(`[data-task="${n}"]`) as HTMLElement
const stepRow = (task: number | null, step: string) =>
  [...(task === null ? document.body : taskBox(task)).querySelectorAll(`[data-step=${step}]`)].at(-1) as HTMLElement

test("run-level steps once at top and bottom", () => {
  show()
  expect(headings()[0]).toBe("At the start")
  expect(headings().at(-1)).toBe("At the end")
  expect(screen.getAllByText("Planner")).toHaveLength(1)
  expect(screen.getAllByText("Summary")).toHaveLength(1)
})

test("finished tasks collapse into one block, the failed one stays open", () => {
  show()
  const done = taskBox(1)
  expect(done.tagName).toBe("DETAILS")
  expect(done).toHaveTextContent("Task 1 · Pricing table")
  expect(done).toHaveTextContent("2 steps passed")
  expect(headings()).toHaveLength(3)
  expect(headings()[1]).toContain("Task 2 · Plan cards")
  expect(headings()[1]).toContain("attempt 2 of 3")
  expect(taskBox(3)).toHaveTextContent("depends on task 2, which failed")
})

test("every attempt gets its own block", () => {
  show()
  expect(within(taskBox(2)).getByText("Builder, attempt 1")).toBeInTheDocument()
  expect(within(taskBox(2)).getByText("Builder, attempt 2")).toBeInTheDocument()
})

test("indicator per step status incl running, waiting and pending", () => {
  const run = runDetail({
    steps: [
      line({ group: "run-start", task: null, step: "planner", status: "passed" }),
      line({ task: 1, status: "running", finished: "" }),
      line({ task: 1, step: "check", status: "waiting" }),
      line({ task: 2, status: "failed" }),
    ],
    tasks: { ...runDetail().tasks, "1": { ...runDetail().tasks["1"]!, status: "running" } },
    gates: [],
  })
  show(run)
  expect(stepRow(1, "builder").querySelector('[data-indicator="running"]')).not.toBeNull()
  expect(stepRow(1, "builder").querySelector(".blk")).toHaveClass("st-run")
  expect(stepRow(1, "check").querySelector('[data-indicator="needs-you"]')).not.toBeNull()
  expect(stepRow(1, "check").querySelector(".blk")).toHaveClass("st-need")
  expect(stepRow(2, "builder").querySelector('[data-indicator="failed"]')).not.toBeNull()
  expect(stepRow(2, "builder").querySelector(".blk")).toHaveClass("st-bad")
  expect(stepRow(null, "planner").querySelector('[data-indicator="passed"]')).not.toBeNull()
  expect(stepRow(2, "check").querySelector(".blk")).toHaveClass("st-pend")
  expect(stepRow(2, "check")).toHaveTextContent("Pending")
})

test("who runs a step: script, you, or the model", () => {
  const run = runDetail()
  run.plan.steps![1] = { ...run.plan.steps![1]!, kind: "ai", ai: { model: "claude-opus-5-5" } } as never
  show(run)
  expect(stepRow(2, "builder")).toHaveTextContent("claude-opus-5-5")
  expect(stepRow(null, "planner")).toHaveTextContent("script")
})

test("a waiting merge step leaves room under it for the review", () => {
  const run = runDetail({
    steps: [line({ group: "run-finish", task: null, step: "merge", status: "waiting", finished: "" })],
    tasks: {}, gates: [],
  })
  run.plan.steps = [{ name: "merge", title: "Merge", group: "run-finish", order: 10, on: true, reason: "", kind: "gate" }] as never
  run.plan.groups = { "run-start": [], task: [], "run-finish": ["merge"] } as never
  show(run)
  expect(stepRow(null, "merge").querySelector("[data-review-room]")).not.toBeNull()
  expect(stepRow(null, "merge")).toHaveTextContent("you")
  // the block and its review share one outlined card, so the orange edge sits inside it
  const card = stepRow(null, "merge").querySelector(".need-card")!
  expect(card.querySelector(".blk")).not.toBeNull()
  expect(card.querySelector("[data-review-room]")).not.toBeNull()
})

test("the waiting merge step shows the open merge question as the review", async () => {
  const gate = { id: "r.1", run: "r", project: "alpha", kind: "merge", title: "Merge Tiny?", why: "", task: null, step: "merge",
    links: [], actions: ["approve", "back", "skip", "stop"], flags: [], created: "", answered: false } as never
  const run = runDetail({
    steps: [line({ group: "run-finish", task: null, step: "merge", status: "waiting", finished: "" })],
    tasks: {}, gates: [gate],
  })
  run.plan.steps = [{ name: "merge", title: "Merge", group: "run-finish", order: 10, on: true, reason: "", kind: "gate" }] as never
  run.plan.groups = { "run-start": [], task: [], "run-finish": ["merge"] } as never
  expect(gatesShownInSteps(run).has("r.1")).toBe(true)
  mockApi({ "GET /api/gates/r.1/review": { gate: "r.1", run: "r", project: "alpha", title: "Merge Tiny?", why: "", answered: false,
    summary: "Does things.", tasks: { passed: 1, total: 1, retried: [] }, full_suite: { status: "passed", note: "" },
    safety: { flag: false, files: [] }, files: [], added: 0, removed: 0, merge_request: "" } })
  renderWithProviders(<StepList run={run} />)
  expect(await within(stepRow(null, "merge")).findByText("Does things.")).toBeInTheDocument()
})

test("switched-off steps show why", () => {
  show()
  const off = stepRow(1, "review")
  expect(off.querySelector('[data-indicator="off"]')).not.toBeNull()
  expect(off).toHaveTextContent("switched off")
})

test("escalation card under its failed step", () => {
  mockApi({})
  renderWithProviders(<StepList run={runDetail()} gates={[openGate]} />)
  const row = stepRow(2, "builder")
  expect(within(row).getByText(openGate.title)).toBeInTheDocument()
  expect(screen.getAllByText(openGate.title)).toHaveLength(1)
  expect(row).toHaveTextContent("the checks failed")
})

test("a long note is cut with an ellipsis and keeps the whole text in its tooltip", () => {
  const note = "x".repeat(300)
  show(runDetail({ steps: [line({ task: 1, status: "failed", note })], gates: [] }))
  expect(stepRow(1, "builder").querySelector(".blk-t span")).toHaveAttribute("title", note)
})

test("unfrozen plan says planned", () => {
  show(runDetail({ plan_frozen: false }))
  expect(screen.getByText("Planned steps; the runner fixes them when the build starts.")).toBeInTheDocument()
})

const repair = (o: object) => ({ n: 1, who: "alex", title: "Put task 2 right", note_id: "1-fix.md", at: "2026-10-31T10:04:00Z", rolled_back: false, ...o })

test("a repair shows as a grey line linked to its note", () => {
  show(runDetail({ repairs: [repair({})] }))
  const link = screen.getByRole("link", { name: "repaired by alex: Put task 2 right" })
  expect(link.getAttribute("href")).toBe(
    "/p/demo-site/logs?run=r-wait&log=r-wait%2Frepairs%2Fnotes%2F1-fix.md")
})

test("a repair sits after the step that ran before it", () => {
  show(runDetail({ repairs: [repair({})] }))
  const row = document.querySelector("[data-repair]")!.parentElement!
  expect(row.getAttribute("data-step")).toBeTruthy()
})

test("an undo has no note, so it is plain text", () => {
  show(runDetail({ repairs: [repair({ note_id: null, title: "Undo repair 1" })] }))
  expect(screen.getByText("repaired by alex: Undo repair 1")).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: /repaired by/ })).toBeNull()
})

test("a resume has no note file, so it is plain text", () => {
  show(runDetail({ repairs: [repair({ note_id: "resume", title: "Resumed" })] }))
  expect(screen.getByText("repaired by alex: Resumed")).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: /repaired by/ })).toBeNull()
})
