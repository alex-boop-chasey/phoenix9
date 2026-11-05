import { act, fireEvent, screen, waitFor } from "@testing-library/react"

import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import type { Gate } from "@/lib/types"
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
    renderWithProviders(<NeedsYouCard gate={merge} />)
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
    renderWithProviders(<NeedsYouCard gate={{ ...escalation, flags: ["delegated to project chat"] }} />)
    const names = screen.getAllByRole("button").map((b) => b.textContent)
    expect(names).toEqual(["Acknowledged", "Skip task", "Stop run"])
    expect(screen.getByText(/Fix it \(for example with the project's chat\)/)).toBeInTheDocument()
    expect(screen.getByText(/The project's chat is working on it/)).toBeInTheDocument()
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
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Answered: Phoenix is carrying on")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("Answered: Phoenix is carrying on")).toBeNull(), { timeout: 3000 })
    expect(screen.queryByText(/Needs you:/)).toBeNull()
  })

  it("409 shows already answered", async () => {
    stubFailure(409, "That question was already answered.")
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Someone already answered this.")).toBeInTheDocument()
  })

  it("error shows plain message", async () => {
    stubFailure(500, "Phoenix could not save that.")
    renderWithProviders(<NeedsYouCard gate={merge} />)
    fireEvent.click(button("Approve"))
    expect(await screen.findByText("Phoenix could not save that.")).toBeInTheDocument()
    expect(button("Approve")).toBeEnabled()
    void act
  })
})
