// Proof: the assistant-ui chat shows streamed text, a project card, a go_to move and an approval, from a mocked stream.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"

import AgentNextPage from "./AgentNextPage"

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

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function setup() {
  render(
    <MemoryRouter initialEntries={["/agent-next"]}>
      <Where />
      <Routes>
        {/* The page stays mounted wherever the agent goes, as the panel will when it sits beside every page. */}
        <Route path="*" element={<AgentNextPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function say(message: string) {
  await userEvent.type(screen.getByLabelText("Message"), message)
  await userEvent.click(screen.getByRole("button", { name: "Send" }))
}

afterEach(() => vi.unstubAllGlobals())

describe("agent-next proof", () => {
  it("streams text and draws the project card", async () => {
    mockService([[started, ...call("c1", "list_projects", "{}"),
      { type: "CUSTOM", name: "component", value: { toolCallId: "c1", component: "project_cards", data: { projects: [{ name: "alpha", state: "idle" }] } } },
      ...text("m1", "You have one project."), finished]])
    setup()
    await say("what projects?")
    expect(await screen.findByText("You have one project.")).toBeInTheDocument()
    expect(await screen.findByTestId("project-cards")).toHaveTextContent("alpha")
  })

  it("go_to checks the page, navigates and posts the browser result", async () => {
    const posts = mockService([
      [started, ...call("g1", "go_to", '{"page":"settings"}')],
      [...text("m2", "Opened it."), finished],
    ])
    setup()
    await say("open settings")
    expect(await screen.findByText("Opened it.")).toBeInTheDocument()
    expect(screen.getByTestId("where")).toHaveTextContent("/settings")
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
    expect(screen.getByTestId("where")).toHaveTextContent("/agent-next")
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
    expect(card).toHaveTextContent("set_notify")
    await userEvent.click(screen.getByRole("button", { name: label }))
    await waitFor(() => expect(posts.find((p) => p.path === "approvals/a1")?.body).toEqual({ decision }))
    expect(await screen.findByText("Done.")).toBeInTheDocument()
  })
})
