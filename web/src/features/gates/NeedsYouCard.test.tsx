import { act, fireEvent, screen, waitFor } from "@testing-library/react"

import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import type { Gate } from "@/lib/types"
import { line, runDetail } from "@/test/buildFixtures"
import { gate as escalation } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const merge: Gate = {
  ...escalation, id: "r.1", kind: "merge", title: "Merge the build", why: "All tasks passed.", task: 2, step: "builder",
  actions: ["approve", "back", "skip", "stop"], flags: ["changes safety code"],
  links: [{ label: "See the changes", url: "https://github.com/x/y/pull/1" }],
}

/** The same merge question with nothing wrong, so Approve answers at once. */
const cleanMerge: Gate = { ...merge, flags: [] }

const answerRoute = (id: string) => ({
  [`POST /api/gates/${id}/answer`]: { gate: id, action: "approve", note: "", who: "alex", at: "" },
})

function stubFailure(status: number, message: string) {
  vi.stubGlobal("fetch", async () =>
    new Response(JSON.stringify({ ok: false, message }), { status, headers: { "Content-Type": "application/json" } }),
  )
}

const button = (name: string | RegExp) => screen.getByRole("button", { name })

describe("NeedsYouCard", () => {
  it("merge gate shows four buttons", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={merge} />)
    expect(screen.getByText("Merge the build")).toBeInTheDocument()
    expect(screen.getByText("Task 2 · Builder step")).toBeInTheDocument()
    for (const n of ["Approve", "Send back with a note", "Skip task", "Stop run"]) expect(button(n)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Acknowledged" })).toBeNull()
  })

  it("shows a gate's own action as a plain button and posts it", async () => {
    const { calls } = mockApi(answerRoute("r.2"))
    const keys: Gate = { ...merge, id: "r.2", kind: "human-task", title: "Paste keys for Supabase",
      actions: ["done", "skip", "stop"] }
    renderWithProviders(<NeedsYouCard gate={keys} />)
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull()
    fireEvent.click(button("Done, keys pasted"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "done", note: "" })
  })

  it("the keys question offers Build without it for now and posts defer", async () => {
    const { calls } = mockApi(answerRoute("r.3"))
    const keys: Gate = { ...merge, id: "r.3", kind: "human-task", title: "Paste keys for Supabase",
      actions: ["done", "defer", "skip", "stop"] }
    renderWithProviders(<NeedsYouCard gate={keys} />)
    expect(button("Done, keys pasted")).toBeInTheDocument()
    expect(screen.getByText(/Waiting for keys/)).toBeInTheDocument()
    fireEvent.click(button("Build without it for now"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "defer", note: "" })
  })

  it("an unknown action is labelled with its own name", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={{ ...merge, actions: ["approve", "deploy"] }} />)
    expect(button("deploy")).toBeInTheDocument()
  })

  it("approve posts approve", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={cleanMerge} />)
    fireEvent.click(button("Approve"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.path).toBe("/api/gates/r.1/answer")
    expect(calls[0]!.body).toEqual({ action: "approve", note: "" })
  })

  it("send back requires a note then posts back with note", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Send back with a note"))
    expect(button("Send back")).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Note for the builder"), { target: { value: "Fix the tests" } })
    expect(button("Send back")).toBeEnabled()
    fireEvent.click(button("Send back"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "back", note: "Fix the tests" })
  })

  it("skip posts skip", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Skip task"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "skip", note: "" })
  })

  it("stop asks for confirmation then posts stop", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Stop run"))
    expect(await screen.findByText("Stop this run?")).toBeInTheDocument()
    expect(calls.length).toBe(0)
    const confirm = screen.getAllByRole("button", { name: "Stop run" }).at(-1)!
    fireEvent.click(confirm)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "stop", note: "" })
  })

  it("escalation shows acknowledged first with help line", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={{ ...escalation, flags: ["handed to the Phoenix agent"] }} />)
    const names = screen.getAllByRole("button").map((b) => b.textContent)
    expect(names).toEqual(["Acknowledged", "Skip task", "Stop run"])
    expect(screen.getByText("Fix it, then press Acknowledged; the task runs once more.")).toBeInTheDocument()
    expect(screen.queryByText(/project's chat/)).toBeNull()
    expect(screen.getByText(/The Phoenix agent has been asked to fix it/)).toBeInTheDocument()
  })

  it("acknowledged posts acknowledged", async () => {
    const { calls } = mockApi(answerRoute(escalation.id))
    renderWithProviders(<NeedsYouCard gate={escalation} />)
    fireEvent.click(button("Acknowledged"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "acknowledged", note: "" })
  })

  it("only actions the gate offers are shown", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={{ ...merge, actions: ["approve"] }} compact />)
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Approve"])
  })

  it("flags shown as badges", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={merge} />)
    expect(screen.getByText("changes safety code")).toBeInTheDocument()
  })

  it("links open in new tab", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={merge} />)
    const link = screen.getByRole("link", { name: "See the changes" })
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("href", "https://github.com/x/y/pull/1")
  })

  it("answered state then disappears", async () => {
    mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={cleanMerge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Answered: Phoenix is carrying on")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("Answered: Phoenix is carrying on")).toBeNull(), { timeout: 3000 })
    expect(screen.queryByText(/Needs you:/)).toBeNull()
  })

  it("409 shows already answered", async () => {
    stubFailure(409, "That question was already answered.")
    renderWithProviders(<NeedsYouCard gate={cleanMerge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Someone already answered this.")).toBeInTheDocument()
  })

  it("error shows plain message", async () => {
    stubFailure(500, "Phoenix could not save that.")
    renderWithProviders(<NeedsYouCard gate={cleanMerge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Phoenix could not save that.")).toBeInTheDocument()
    expect(button("Approve")).toBeEnabled()
    void act
  })

  it("approve on a merge with flags asks first, lists them and merges on Merge anyway", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={{ ...merge, flags: ["full suite did not pass", "handed to the Phoenix agent"] }} />)
    fireEvent.click(button("Approve"))
    const list = await screen.findByRole("list", { name: "What went wrong" })
    expect(list.textContent).toBe("Full suite did not pass")
    expect(calls.length).toBe(0)
    fireEvent.click(button("Merge anyway"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "approve", note: "" })
  })

  it("approve on a merge whose run has a failed or skipped part asks first; Cancel sends nothing", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    const base = runDetail()
    const run = runDetail({
      tasks: { "1": { ...base.tasks["1"]!, status: "passed" }, "4": { ...base.tasks["1"]!, status: "skipped" } },
      steps: [line({ group: "run-finish", task: null, step: "full-suite", status: "failed" })],
    })
    renderWithProviders(<NeedsYouCard gate={cleanMerge} run={run} />)
    fireEvent.click(button("Approve"))
    const items = await screen.findAllByRole("listitem")
    expect(items.map((i) => i.textContent)).toEqual(["Task 4 was skipped", "Final test run failed"])
    fireEvent.click(button("Cancel"))
    await waitFor(() => expect(screen.queryByRole("list", { name: "What went wrong" })).toBeNull())
    expect(calls.length).toBe(0)
  })

  it("approve on a question that is not a merge never asks, flags or not", async () => {
    const { calls } = mockApi(answerRoute("r.1"))
    renderWithProviders(<NeedsYouCard gate={{ ...merge, kind: "plan", flags: ["changes safety code"] }} />)
    fireEvent.click(button("Approve"))
    await waitFor(() => expect(calls.length).toBe(1))
  })
})

const unlock: Gate = {
  ...escalation, id: "r-fail.4", run: "r-fail", kind: "repair-unlock", task: null, step: null, links: [], flags: [],
  title: "The agent asks to reset the worktree and force a repair past its check on r-fail: the worktree is stuck",
  why: "the worktree is stuck", actions: ["approve", "deny"], unlock_steps: ["reset-worktree", "force"], asked_by: "agent",
}

describe("NeedsYouCard: the agent asks to unlock a repair", () => {
  it("shows the run, the repairs in plain words, the reason and Allow once / Don't allow", () => {
    mockApi({})
    renderWithProviders(<NeedsYouCard gate={unlock} />)
    const body = screen.getByTestId("repair-unlock")
    expect(body).toHaveTextContent("The Phoenix agent asks you to allow, once, a repair it may not do alone on build r-fail")
    const items = screen.getByRole("list", { name: "Repairs asked for" }).querySelectorAll("li")
    expect([...items].map((i) => i.textContent)).toEqual(["reset the worktree", "force a repair past its check"])
    expect(body).toHaveTextContent("Why: the worktree is stuck")
    expect(screen.getByText("Repair")).toBeInTheDocument()
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Allow once", "Don't allow"])
  })

  it("Allow once asks first; Cancel sends nothing, confirming sends approve", async () => {
    const { calls } = mockApi(answerRoute("r-fail.4"))
    renderWithProviders(<NeedsYouCard gate={unlock} />)
    fireEvent.click(button("Allow once"))
    expect(await screen.findByText(/The Phoenix agent may then reset the worktree and force a repair past its check on this build, one time/)).toBeInTheDocument()
    fireEvent.click(button("Cancel"))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Yes, allow once" })).toBeNull())
    expect(calls.length).toBe(0)
    fireEvent.click(button("Allow once"))
    fireEvent.click(await screen.findByRole("button", { name: "Yes, allow once" }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "approve", note: "" })
    expect(await screen.findByText(/Allowed once/)).toBeInTheDocument()
  })

  it("Don't allow sends deny at once", async () => {
    const { calls } = mockApi(answerRoute("r-fail.4"))
    renderWithProviders(<NeedsYouCard gate={{ ...unlock, asked_by: "chat:demo-site" }} />)
    expect(screen.getByTestId("repair-unlock")).toHaveTextContent("A chat in demo-site asks you")
    fireEvent.click(button("Don't allow"))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]!.body).toEqual({ action: "deny", note: "" })
    expect(await screen.findByText(/Not allowed/)).toBeInTheDocument()
  })
})
