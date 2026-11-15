// Proof: the assistant-ui chat shows streamed text, a project card, a go_to move and an approval, from a mocked stream.
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { renderFullAgent } from "@/test/agentPanel"

type Ev = Record<string, unknown>
const frame = (n: number, e: Ev) => `id: ${n}\ndata: ${JSON.stringify(e)}\n\n`
const started: Ev = { type: "RUN_STARTED", threadId: "t1", runId: "r1" }
const text = (id: string, t: string): Ev[] => [
  { type: "TEXT_MESSAGE_START", messageId: id, role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: id, delta: t },
  { type: "TEXT_MESSAGE_END", messageId: id },
]
const call = (id: string, name: string, args: string): Ev[] => [
  { type: "TOOL_CALL_START", toolCallId: id, toolCallName: name },
  { type: "TOOL_CALL_ARGS", toolCallId: id, delta: args },
  { type: "TOOL_CALL_END", toolCallId: id },
]
const finished: Ev = { type: "RUN_FINISHED", threadId: "t1", runId: "r1" }

/** Fake agent service: streams[i] answers the i-th stream request; posts are recorded. */
function mockService(streams: Ev[][]) {
  const posts: { path: string; body: any }[] = []
  let streamCall = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost/")
    const path = url.pathname.replace(/^.*agent-next\//, "")
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) : {}
      posts.push({ path, body })
      return new Response(JSON.stringify(path === "threads" ? { id: "t1" } : {}), { status: 200 })
    }
    if (!url.pathname.endsWith("/stream")) return new Response(JSON.stringify({ threads: [] }), { status: 200 })
    const events = streams[streamCall++] ?? [finished]
    const body = events.map((e, i) => frame(i + 1 + (streamCall - 1) * 100, e)).join("")
    return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  return posts
}

/** The full-screen panel; it moves the dashboard through the address hash (the app's router) and stays open. */
function setup() {
  renderFullAgent()
}

async function say(message: string) {
  await userEvent.type(screen.getByLabelText("Message"), message)
  await userEvent.click(screen.getByRole("button", { name: "Send" }))
}

afterEach(() => { vi.unstubAllGlobals(); window.location.hash = "" })

describe("agent-next proof", () => {
  const chips: Ev = { type: "CUSTOM", name: "suggestions", value: { actions: [{ label: "Cancel", message: "cancel" }, { label: "Pick a name", message: "name" }] } }
  const flowCard: Ev = { type: "CUSTOM", name: "component", value: { toolCallId: "f1", component: "FlowCard",
    data: { flow: "new", status: "active", step: 1, steps: 5, label: "Name the project", values: { goal: "Android app" } } } }

  it("hides a Cancel chip while a flow is active: the flow card has the only Cancel", async () => {
    mockService([[started, flowCard, chips, ...text("m1", "What should it be called?"), finished]])
    setup()
    await say("I want a new Android app")
    expect(await screen.findByText("What should it be called?")).toBeInTheDocument()
    const strip = await screen.findByTestId("suggestion-chips")
    expect(within(strip).getByRole("button", { name: "Pick a name" })).toBeInTheDocument()
    expect(within(strip).queryByRole("button", { name: "Cancel" })).toBeNull()
    expect(screen.getAllByRole("button", { name: "Cancel" })).toHaveLength(1)
    expect(within(screen.getByTestId("flow-card")).getByTestId("flow-fact")).toHaveTextContent("Goal: Android app")
  })

  it("shows a Cancel chip when no flow is active", async () => {
    mockService([[started, chips, ...text("m1", "Anything else?"), finished]])
    setup()
    await say("hello")
    expect(await screen.findByText("Anything else?")).toBeInTheDocument()
    expect(within(await screen.findByTestId("suggestion-chips")).getByRole("button", { name: "Cancel" })).toBeInTheDocument()
  })

  it("streams text and draws the project card", async () => {
    mockService([[started, ...call("c1", "list_projects", "{}"),
      { type: "CUSTOM", name: "component", value: { toolCallId: "c1", component: "project_cards", data: { projects: [{ name: "alpha", state: "idle" }] } } },
      ...text("m1", "You have one project."), finished]])
    setup()
    await say("what projects?")
    expect(await screen.findByText("You have one project.")).toBeInTheDocument()
    expect(await screen.findByTestId("project-cards")).toHaveTextContent("alpha")
  })

  it("shows what it did as a closed list of plain steps, never the tool ids", async () => {
    const done = (id: string): Ev => ({ type: "TOOL_CALL_RESULT", messageId: `r-${id}`, toolCallId: id, content: "{}" })
    mockService([[started, ...call("s1", "library-profiles", "{}"), done("s1"), ...call("s2", "projects-list", "{}"), done("s2"),
      ...call("s3", "suggest_next_actions", "{}"), done("s3"), ...text("m1", "Here is what I found."), finished]])
    setup()
    await say("I want a new Android app")
    expect(await screen.findByText("Here is what I found.")).toBeInTheDocument()
    const steps = await screen.findByTestId("agent-steps")
    expect(steps).not.toHaveAttribute("open")
    expect(within(steps).getByText("3 steps")).toBeInTheDocument()
    await userEvent.click(within(steps).getByText("3 steps"))
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent))
      .toEqual(["Checked project types", "Looked at your projects", "Suggested next steps"])
    expect(screen.queryByText(/library-profiles|projects-list|suggest_next_actions/)).toBeNull()
  })

  it("go_to checks the page, navigates and posts the browser result", async () => {
    const posts = mockService([
      [started, ...call("g1", "go_to", '{"page":"settings"}')],
      [...text("m2", "Opened it."), finished],
    ])
    setup()
    await say("open settings")
    expect(await screen.findByText("Opened it.")).toBeInTheDocument()
    expect(window.location.hash).toBe("#/settings")
    expect(screen.getByLabelText("Phoenix agent panel")).toHaveClass("open")
    const result = posts.find((p) => p.path === "browser-results/g1")
    expect(result?.body.result).toMatchObject({ ok: true })
  })

  it("refuses an unknown page and stays where it is", async () => {
    const posts = mockService([
      [started, ...call("g2", "go_to", '{"page":"nowhere"}')],
      [...text("m3", "I could not."), finished],
    ])
    setup()
    await say("open nowhere")
    expect(await screen.findByText("I could not.")).toBeInTheDocument()
    expect(window.location.hash).toBe("")
    expect(posts.find((p) => p.path === "browser-results/g2")?.body.result).toMatchObject({ ok: false })
  })

  it.each([["Approve", "approve"], ["Deny", "deny"]])("%s sends the decision and the run goes on", async (label, decision) => {
    const posts = mockService([
      [started, { type: "CUSTOM", name: "approval_request", value: { approvalId: "a1", toolCallId: "t9", toolName: "set_notify", input: { on: true } } }],
      [...text("m4", "Done."), finished],
    ])
    setup()
    await say("turn on notify")
    const card = await screen.findByTestId("approval-card")
    expect(card).toHaveTextContent("A change")
    expect(card).not.toHaveTextContent("set_notify")
    await userEvent.click(screen.getByRole("button", { name: label }))
    await waitFor(() => expect(posts.find((p) => p.path === "approvals/a1")?.body).toEqual({ decision }))
    expect(await screen.findByText("Done.")).toBeInTheDocument()
  })

  it("an approval_request with a description and typed text shows both and posts confirm", async () => {
    const posts = mockService([
      [started, { type: "CUSTOM", name: "approval_request", value: { approvalId: "a2", toolCallId: "t8", toolName: "stop-build", description: "Stop the running build.", input: { name: "alpha" }, confirm_text: "alpha" } }],
      [...text("m5", "Stopped."), finished],
    ])
    setup()
    await say("stop it")
    expect(await screen.findByText("Stop the running build.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled()
    await userEvent.type(screen.getByLabelText("Type alpha to confirm"), "alpha")
    await userEvent.click(screen.getByRole("button", { name: "Approve" }))
    await waitFor(() => expect(posts.find((p) => p.path === "approvals/a2")?.body).toEqual({ decision: "approve", confirm: "alpha" }))
  })
})
