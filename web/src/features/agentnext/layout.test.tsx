// The /agent-next layout: history list, opening a thread, new conversation, Stop and the allowance bar.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"

import AgentNextPage from "./AgentNextPage"

const frame = (n: number, e: Record<string, unknown>) => `id: ${n}\ndata: ${JSON.stringify(e)}\n\n`

/** Fake agent service. A stream request on t1 sends one event and then hangs, as a running reply does. */
function mockService(state: "plenty" | "low" | "used_up" = "plenty") {
  const posts: string[] = []
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost/").pathname.replace(/^.*agent-next\//, "")
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
    if (init?.method === "POST") {
      posts.push(path)
      return json(path === "threads" ? { id: "t9" } : {})
    }
    if (path === "threads") return json({ threads: [
      { id: "t1", title: "Check my projects", created: 1, last_used: 1700000000 },
      { id: "t2", title: "Settings question", created: 1, last_used: 1600000000 },
    ] })
    if (path === "spend") return json({ month: "2026-11", used_share: state === "plenty" ? 0.2 : state === "low" ? 0.85 : 1, state })
    if (path === "threads/t2") return json({ thread: { id: "t2" }, running: false, events: [
      { number: 1, event: { type: "CUSTOM", name: "user_message", value: { id: "u1", text: "Where is the doctor?" } } },
      { number: 2, event: { type: "TEXT_MESSAGE_START", messageId: "a1", role: "assistant" } },
      { number: 3, event: { type: "TEXT_MESSAGE_CONTENT", messageId: "a1", delta: "It is under Health." } },
      { number: 4, event: { type: "TEXT_MESSAGE_END", messageId: "a1" } },
    ] })
    if (path.endsWith("/stream")) {
      const enc = new TextEncoder()
      const body = new ReadableStream({ start(c) {
        c.enqueue(enc.encode(frame(1, { type: "RUN_STARTED", threadId: "t9", runId: "r1" })))
      } })
      return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } })
    }
    return json({})
  }))
  return posts
}

function setup() {
  render(<MemoryRouter initialEntries={["/agent-next"]}><AgentNextPage /></MemoryRouter>)
}

afterEach(() => vi.unstubAllGlobals())

describe("agent-next layout", () => {
  it("lists earlier conversations with title and last used", async () => {
    mockService()
    setup()
    expect(await screen.findByText("Check my projects")).toBeInTheDocument()
    expect(screen.getByText("Settings question")).toBeInTheDocument()
    expect(screen.getAllByText(/Last used/)).toHaveLength(2)
  })

  it("opens a thread when clicked", async () => {
    mockService()
    setup()
    await userEvent.click(await screen.findByText("Settings question"))
    expect(await screen.findByText("Where is the doctor?")).toBeInTheDocument()
    expect(await screen.findByText("It is under Health.")).toBeInTheDocument()
  })

  it("starts a new conversation with an empty chat", async () => {
    mockService()
    setup()
    await userEvent.click(await screen.findByText("Settings question"))
    await screen.findByText("It is under Health.")
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }))
    await waitFor(() => expect(screen.queryByText("It is under Health.")).not.toBeInTheDocument())
  })

  it("shows Stop only while a run is going and Stop calls the stop route", async () => {
    const posts = mockService()
    setup()
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Message"), "hello")
    await userEvent.click(screen.getByRole("button", { name: "Send" }))
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }))
    await waitFor(() => expect(posts).toContain("threads/t9/stop"))
  })

  it.each([
    ["plenty", "plenty left this month"],
    ["low", "getting low"],
    ["used_up", "used up this month"],
  ] as const)("allowance %s says it in words with no dollar sign", async (state, words) => {
    mockService(state)
    setup()
    expect(await screen.findByText(words)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain("$")
  })
})
