import { act, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useLocation } from "react-router"

import { runDetail } from "@/test/buildFixtures"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import { wizardPlan, wizardPresets, wizardSettings, wizardSpecs, wizardSteps } from "@/test/wizardFixtures"

import { BuildTab } from "../BuildTab"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const P = "notes-only"
const routes = (over: Record<string, unknown> = {}) => ({
  [`GET /api/projects/${P}/settings`]: wizardSettings(),
  "GET /api/library/presets": { presets: wizardPresets },
  "GET /api/library/steps": { steps: wizardSteps, problems: [] },
  [`GET /api/projects/${P}/specs`]: wizardSpecs,
  [`POST /api/projects/${P}/plan`]: (req: MockRequest) => wizardPlan((req.body as { overrides: Record<string, unknown> }).overrides),
  [`GET /api/projects/${P}/runs`]: [],
  "GET /api/events/recent": { events: [], next: 0 },
  ...over,
})

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}
const show = () => renderWithProviders(<><BuildTab name={P} /><Where /></>, { route: `/p/${P}/build?new=1` })

const title = () => screen.getByRole("heading", { level: 2 }).textContent
const next = () => userEvent.click(screen.getByRole("button", { name: "Next" }))
const back = () => userEvent.click(screen.getByRole("button", { name: "Back" }))
const sw = (name: string) => screen.getByRole("switch", { name })

async function pickSpec() {
  await screen.findByText("Step 1 of 7")
  await userEvent.click(await screen.findByRole("radio", { name: "Reading plan" }))
}

/** Go from slide 1 to slide n with the spec picked. */
async function goTo(n: number) {
  await pickSpec()
  for (let i = 1; i < n; i++) {
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
    await next()
  }
  await screen.findByText(`Step ${n} of 7`)
}

const planBodies = (calls: MockRequest[]) =>
  calls.filter((c) => c.method === "POST" && c.path.endsWith("/plan")).map((c) => (c.body as { overrides: Record<string, unknown> }).overrides)

test("next and back keep answers across all seven slides", async () => {
  mockApi(routes())
  show()
  await pickSpec()
  expect(screen.getByRole("button", { name: "Back" })).toBeDisabled()
  await next()
  expect(title()).toBe("Preset")
  await next()
  await waitFor(() => expect(sw("Reviewer")).toBeEnabled())
  await userEvent.click(sw("Reviewer"))
  await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
  await next()
  await next()
  const tries = screen.getByLabelText("Tries per task (1 to 10)")
  await userEvent.clear(tries)
  await userEvent.type(tries, "2")
  await userEvent.click(screen.getByRole("radio", { name: "Continue" }))
  await next()
  await userEvent.click(sw("Notifications"))
  await next()
  expect(title()).toBe("Review and submit")
  for (let n = 7; n > 1; n--) await back()
  expect(screen.getByRole("radio", { name: "Reading plan" })).toBeChecked()
  await next()
  expect(screen.getByRole("radio", { name: "Custom" })).toBeChecked()
  await next()
  expect(sw("Reviewer")).toBeChecked()
  await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
  await next()
  await next()
  expect(screen.getByLabelText("Tries per task (1 to 10)")).toHaveValue(2)
  expect(screen.getByRole("radio", { name: "Continue" })).toBeChecked()
  await next()
  expect(sw("Notifications")).not.toBeChecked()
})

test("effective step list refetched (debounced) when answers change", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const { calls } = mockApi(routes())
  show()
  await goTo(2)
  await act(() => vi.advanceTimersByTimeAsync(400))
  const before = planBodies(calls).length
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  await user.click(screen.getByRole("radio", { name: "Full" }))
  await user.click(screen.getByRole("radio", { name: "Simple" }))
  await user.click(screen.getByRole("radio", { name: "Full" }))
  await act(() => vi.advanceTimersByTimeAsync(100))
  const wizardCalls = () => planBodies(calls).slice(before).filter((o) => o.steps)
  expect(wizardCalls()).toHaveLength(0)
  await act(() => vi.advanceTimersByTimeAsync(400))
  await waitFor(() => expect(wizardCalls()).toHaveLength(1))
  expect(wizardCalls()[0]!.preset).toBe("full")
  const rail = screen.getByRole("list", { name: "Effective steps" })
  await waitFor(() => expect(within(rail).getByText(/Reviewer/, { selector: "b" })).toBeInTheDocument())
  expect(rail.querySelector("[data-off]")).toBeNull()
})

test("always-on steps locked", async () => {
  mockApi(routes())
  show()
  await goTo(3)
  await waitFor(() => expect(sw("Builder")).toBeChecked())
  expect(sw("Builder")).toBeDisabled()
  const row = sw("Builder").closest("label")!
  expect(within(row).getByText("always on")).toBeInTheDocument()
  expect(sw("Verify")).toBeEnabled()
  expect(within(sw("Verify").closest("label")!).getByText("Safety")).toBeInTheDocument()
})

test("forced-off step shows reason", async () => {
  mockApi(routes({
    [`POST /api/projects/${P}/plan`]: (req: MockRequest) => {
      const o = (req.body as { overrides: Record<string, unknown> }).overrides
      const plan = wizardPlan(o)
      return o.steps && (o.steps as Record<string, { on: boolean }>).reviewer?.on
        ? { ...plan, errors: ["Reviewer needs a test report, which nothing makes"] } : plan
    },
  }))
  show()
  await goTo(3)
  await screen.findByText("Switched off by another step")
  expect(screen.getAllByText(/needs check-writer, which is off/).length).toBeGreaterThan(0)
  expect(sw("Red check")).not.toBeChecked()
  await userEvent.click(sw("Reviewer"))
  expect(await screen.findByText("Reviewer needs a test report, which nothing makes")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled()
  expect(screen.getAllByText(/Custom, based on Quick/).length).toBeGreaterThan(0)
})

test("models slide: one card per AI step that is on, opened by Model and tools", async () => {
  mockApi(routes({ [`GET /api/projects/${P}/settings`]: wizardSettings({ preset: "full", steps: { planner: { on: true }, "check-writer": { on: true }, reviewer: { on: true } } }) }))
  show()
  await goTo(4)
  await screen.findByText("claude-fable-5-1")
  const cards = [...document.querySelectorAll(".aic")].map((c) => c.getAttribute("data-step"))
  expect(cards).toEqual(["planner", "check-writer", "builder", "reviewer"])
  const builder = within(screen.getByRole("group", { name: "Builder" }))
  expect(screen.queryByLabelText("Model")).toBeNull()
  await userEvent.click(builder.getByRole("button", { name: "Model and tools" }))
  expect(builder.getByLabelText("Model")).toHaveValue("claude-fable-5-1")
  expect(builder.getByLabelText("Fallback model 1")).toHaveValue("claude-sonnet-5-5")
  await userEvent.selectOptions(builder.getByLabelText("Model"), "claude-opus-5-5")
  await userEvent.click(builder.getByRole("button", { name: "Add a fallback model" }))
  expect(builder.getByLabelText("Fallback model 2")).toBeInTheDocument()
  await userEvent.click(builder.getByRole("button", { name: "Move fallback 2 up" }))
  await userEvent.click(builder.getByRole("button", { name: "Remove fallback 1" }))
  expect(builder.queryByLabelText("Fallback model 2")).toBeNull()
  await userEvent.click(builder.getByRole("switch", { name: "Web search" }))
  expect(builder.getByRole("switch", { name: "Web search" })).toBeChecked()
  await userEvent.clear(builder.getByLabelText("Turn limit"))
  await userEvent.type(builder.getByLabelText("Turn limit"), "99")
  await userEvent.click(builder.getByRole("button", { name: "Close" }))
  expect(builder.queryByLabelText("Model")).toBeNull()
})

test("models slide leaves out AI steps that are switched off", async () => {
  mockApi(routes())
  show()
  await goTo(4)
  await screen.findByRole("group", { name: "Builder" })
  expect(screen.queryByRole("group", { name: "Reviewer" })).toBeNull()
  expect(screen.queryByRole("group", { name: "Planner" })).toBeNull()
})

test("the outline jumps back to seen steps and shows their summary", async () => {
  mockApi(routes())
  show()
  await goTo(3)
  const outline = screen.getByRole("list", { name: "Build wizard steps" })
  expect(within(outline).getByRole("button", { name: /Preset/ })).toHaveTextContent("Quick")
  expect(within(outline).getByRole("button", { name: /Failures/ })).toBeDisabled()
  await userEvent.click(within(outline).getByRole("button", { name: /What to build/ }))
  expect(screen.getByText("Step 1 of 7")).toBeInTheDocument()
})

test("step 2 rail shows what runs and why the rest is off", async () => {
  mockApi(routes())
  show()
  await goTo(2)
  const rail = await screen.findByRole("list", { name: "Effective steps" })
  await waitFor(() => expect(within(rail).getByText("Off in Quick")).toBeInTheDocument())
  expect(within(rail).getByText("At the start")).toBeInTheDocument()
  expect(within(rail).getByText("For every task")).toBeInTheDocument()
  expect(within(rail).getByText("At the end")).toBeInTheDocument()
  expect(rail.querySelector("[data-off] b")).toHaveTextContent("Planner")
  await userEvent.click(screen.getByRole("radio", { name: "Custom" }))
  expect(await within(rail).findByText("Switched off on the Steps page")).toBeInTheDocument()
  expect(screen.getByText(/Custom: switch each step on or off/)).toBeInTheDocument()
})

test("steps 2 and 3 share one state: a switch makes Custom and updates the rail", async () => {
  mockApi(routes())
  show()
  await goTo(3)
  await waitFor(() => expect(sw("Reviewer")).toBeEnabled())
  await userEvent.click(sw("Reviewer"))
  await back()
  expect(screen.getByRole("radio", { name: "Custom" })).toBeChecked()
  const rail = screen.getByRole("list", { name: "Effective steps" })
  expect(within(rail).getByText(/Reviewer/, { selector: "b" })).toBeInTheDocument()
  expect(rail).toBeInTheDocument()
})

test("red check needs check writer: a dependency note, and it follows the switch", async () => {
  mockApi(routes())
  show()
  await goTo(3)
  await screen.findByText("Can't run: needs Check writer (switch it on)")
  expect(sw("Red check")).toBeDisabled()
})

test("a brief locks the Planner on with a note", async () => {
  mockApi(routes())
  show()
  await screen.findByText("Step 1 of 7")
  await userEvent.click(screen.getByRole("radio", { name: "Write a brief for the Planner" }))
  await userEvent.type(screen.getByLabelText("Brief"), "A reading list")
  await next()
  await next()
  await waitFor(() => expect(sw("Planner")).toBeChecked())
  expect(sw("Planner")).toBeDisabled()
  expect(screen.getByText("On because you chose to write a brief on step 1")).toBeInTheDocument()
})

test("failure modes explained", async () => {
  mockApi(routes())
  show()
  await goTo(5)
  for (const t of ["Continue", "Pause for me", "Delegate to the project chat"]) {
    expect(screen.getByRole("radio", { name: t })).toBeInTheDocument()
  }
  expect(screen.getByText(/Move on to tasks that don't depend/)).toBeInTheDocument()
  expect(screen.getByText(/press Acknowledged when fixed/)).toBeInTheDocument()
  expect(screen.getByText(/only alerts you if it can't/)).toBeInTheDocument()
  expect(screen.getByRole("radio", { name: "Pause for me" })).toBeChecked()
  const tries = screen.getByLabelText("Tries per task (1 to 10)")
  await userEvent.clear(tries)
  await userEvent.type(tries, "11")
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled()
})

test("review lists the plan in order with off steps greyed", async () => {
  mockApi(routes())
  show()
  await goTo(7)
  const plan = screen.getByRole("region", { name: "Plan" })
  const names = [...plan.querySelectorAll("li")].map((li) => li.getAttribute("data-step"))
  expect(names).toEqual(["pick-up", "spec-check", "planner", "check-writer", "red-check", "builder", "diff-rules", "verify",
    "reviewer", "summary", "merge", "notify"])
  const reviewer = plan.querySelector("[data-step=reviewer]")!
  expect(reviewer).toHaveAttribute("data-on", "false")
  expect(reviewer).toHaveClass("line-through")
  expect(plan.querySelector("[data-step=verify]")).toHaveAttribute("data-on", "true")
  expect(screen.getByText("Reading plan (specs/reading-plan.md)")).toBeInTheDocument()
  expect(screen.getByRole("switch", { name: "Remember these as this project's defaults" })).toBeChecked()
})

test("submit with remember posts defaults then runs then shows running view", async () => {
  const { calls } = mockApi(routes({
    [`POST /api/projects/${P}/defaults`]: { project: P },
    [`POST /api/projects/${P}/runs`]: { run_id: "r-new", project: P, status: "queued" },
    [`GET /api/runs/${P}/r-new`]: runDetail({ run_id: "r-new", project: P, status: "queued", steps: [], gates: [], plan_frozen: false }),
  }))
  show()
  await goTo(5)
  const tries = screen.getByLabelText("Tries per task (1 to 10)")
  await userEvent.clear(tries)
  await userEvent.type(tries, "2")
  await next()
  await next()
  await userEvent.click(screen.getByRole("button", { name: "Start build" }))
  await screen.findByText("Queued: waiting for the runner to pick it up.")
  expect(screen.getByTestId("where")).toHaveTextContent(`/p/${P}/build?run=r-new`)
  const posts = calls.filter((c) => c.method === "POST" && !c.path.endsWith("/plan"))
  expect(posts.map((c) => c.path)).toEqual([`/api/projects/${P}/defaults`, `/api/projects/${P}/runs`])
  const defaults = (posts[0]!.body as { overrides: Record<string, unknown> }).overrides
  expect(defaults).toMatchObject({ preset: "quick", max_tries: 2 })
  expect(defaults).not.toHaveProperty("spec")
  expect(posts[1]!.body).toEqual({ spec: "specs/reading-plan.md", overrides: defaults })
})

test("submit without remember posts only runs", async () => {
  const { calls } = mockApi(routes({
    [`POST /api/projects/${P}/runs`]: { run_id: "r-new", project: P, status: "queued" },
    [`GET /api/runs/${P}/r-new`]: runDetail({ run_id: "r-new", project: P, status: "queued", steps: [], gates: [] }),
  }))
  show()
  await goTo(7)
  await userEvent.click(screen.getByRole("switch", { name: "Remember these as this project's defaults" }))
  await userEvent.click(screen.getByRole("button", { name: "Start build" }))
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("run=r-new"))
  const posts = calls.filter((c) => c.method === "POST" && !c.path.endsWith("/plan")).map((c) => c.path)
  expect(posts).toEqual([`/api/projects/${P}/runs`])
})

test("submit error keeps answers and shows message", async () => {
  const fail = () => new Response(JSON.stringify({ ok: false, message: "The spec has to be a file in notes/specs." }), { status: 400 })
  const { fetch } = mockApi(routes({ [`POST /api/projects/${P}/defaults`]: { project: P } }))
  const real = fetch.getMockImplementation()!
  fetch.mockImplementation(async (input, init) =>
    String(input).endsWith(`/projects/${P}/runs`) && init?.method === "POST" ? fail() : real(input, init))
  show()
  await goTo(7)
  await userEvent.click(screen.getByRole("button", { name: "Start build" }))
  expect(await screen.findByText("The spec has to be a file in notes/specs.")).toBeInTheDocument()
  expect(title()).toBe("Review and submit")
  expect(screen.getByText("Reading plan (specs/reading-plan.md)")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Start build" })).toBeEnabled()
})

test("brief switches the planner on with a note", async () => {
  mockApi(routes())
  show()
  await screen.findByText("Step 1 of 7")
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled()
  await userEvent.click(screen.getByRole("radio", { name: "Write a brief for the Planner" }))
  expect(screen.getByText(/The Planner turns your brief into a spec/)).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText("Brief"), "Add a reading list page")
  await next()
  await next()
  await waitFor(() => expect(sw("Planner")).toBeChecked())
})

test("phoenix9 merge is locked to ask", async () => {
  mockApi({
    ...routes(),
    "GET /api/projects/phoenix9/settings": wizardSettings({ merge: "ask" }, "phoenix9"),
    "GET /api/projects/phoenix9/specs": wizardSpecs,
    "POST /api/projects/phoenix9/plan": (req: MockRequest) => wizardPlan((req.body as { overrides: Record<string, unknown> }).overrides),
    "GET /api/projects/phoenix9/runs": [],
  })
  renderWithProviders(<BuildTab name="phoenix9" />, { route: "/p/phoenix9/build?new=1" })
  await goTo(6)
  expect(screen.getByRole("radio", { name: "Ask me first" })).toBeChecked()
  expect(screen.getByRole("radio", { name: "Merge automatically" })).toBeDisabled()
  expect(sw("Deploy")).toBeDisabled()
  expect(screen.getByText("Deployers come later.")).toBeInTheDocument()
})

test("picking Quick turns off a step the project's saved settings switched on", async () => {
  const saved = { steps: { reviewer: true } }
  mockApi(routes({
    [`GET /api/projects/${P}/settings`]: wizardSettings({ steps: { reviewer: { on: true } } }),
    [`POST /api/projects/${P}/plan`]: (req: MockRequest) =>
      wizardPlan((req.body as { overrides: Record<string, unknown> }).overrides, saved),
  }))
  show()
  await goTo(2)
  await userEvent.click(screen.getByRole("radio", { name: "Full" }))
  await userEvent.click(screen.getByRole("radio", { name: "Quick" }))
  expect(screen.getByRole("radio", { name: "Quick" })).toBeChecked()
  await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
  await next()
  await waitFor(() => expect(sw("Reviewer")).not.toBeChecked())
  expect(sw("Verify")).toBeChecked()
})

test("Next waits on the Steps slide while the step list is updating", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi(routes())
  show()
  await goTo(3)
  await act(() => vi.advanceTimersByTimeAsync(400))
  await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  await user.click(sw("Verify"))
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled()
  await act(() => vi.advanceTimersByTimeAsync(400))
  await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled())
})

test("slide 1 says what is missing", async () => {
  mockApi(routes())
  show()
  expect(await screen.findByText("Choose a spec to build.")).toBeInTheDocument()
})

test("preset slide shows each preset's title and description", async () => {
  mockApi(routes())
  show()
  await goTo(2)
  for (const p of wizardPresets) {
    expect(screen.getByRole("radio", { name: p.title })).toBeInTheDocument()
    expect(screen.getByText(p.description)).toBeInTheDocument()
  }
})
