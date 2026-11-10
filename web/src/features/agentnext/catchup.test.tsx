// The /agent-next panel catches up after a reload or a dropped line, and explains a missing agent in plain words.
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"

import AgentNextPage from "./AgentNextPage"

type Ev = Record<string, unknown>
const enc = new TextEncoder()
const frame = (n: number, e: Ev) => `id: ${n}\ndata: ${JSON.stringify(e)}\n\n`
const user: Ev = { type: "CUSTOM", name: "user_message", value: { id: "u1", text: "Check my builds" } }
const start: Ev = { type: "TEXT_MESSAGE_START", messageId: "a1", role: "assistant" }
const word = (d: string): Ev => ({ type: "TEXT_MESSAGE_CONTENT", messageId: "a1", delta: d })
const finished: Ev = { type: "RUN_FINISHED", threadId: "t1", runId: "r1" }

interface Options { status?: Response; stored: [number, Ev][]; running: boolean; streams?: [number, Ev][][] }

/** Fake agent service. Each stream request answers with the next list of frames, then ends (a dropped line). */
function mockService(o: Options) {
  const afters: string[] = []
  let n = 0
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost/")
    const path = url.pathname.replace(/^.*agent-next\//, "")
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
    if (path === "status") return o.status ?? json({ running: true, key_present: true, pack: "phoenix", model: "m" })
    if (path === "threads") return json({ threads: [{ id: "t1", title: "Check my builds", created: 1, last_used: 1 }] })
    if (path === "spend") return json({ month: "2026-11", used_share: 0.1, state: "plenty" })
    if (path === "threads/t1") return json({ thread: { id: "t1" }, running: o.running, events: o.stored.map(([number, event]) => ({ number, event })) })
    if (path === "threads/t1/stream") {
      afters.push(url.searchParams.get("after") ?? "")
      const frames = (o.streams ?? [])[n++] ?? []
      return new Response(new ReadableStream({ start(c) {
        for (const [num, e] of frames) c.enqueue(enc.encode(frame(num, e)))
        c.close()
      } }), { status: 200, headers: { "Content-Type": "text/event-stream" } })
    }
    return json({})
  }))
  return afters
}

function setup() {
  render(<MemoryRouter initialEntries={["/agent-next"]}><AgentNextPage /></MemoryRouter>)
}

beforeEach(() => localStorage.setItem("agent-next-thread", "t1"))
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

describe("agent-next catching up", () => {
  it("shows the whole conversation after a reload and follows a run still going to its end", async () => {
    const afters = mockService({
      running: true,
      stored: [[1, user], [2, start], [3, word("Looking ")]],
      streams: [[[4, word("now.")], [5, finished]]],
    })
    setup()
    expect(await screen.findByText("Check my builds", { selector: "p" })).toBeInTheDocument()
    expect(await screen.findByText("Looking now.")).toBeInTheDocument()
    expect(afters).toEqual(["3"])
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument())
  })

  it("reconnects from the last number with no repeats and no gaps", async () => {
    const afters = mockService({
      running: true,
      stored: [[1, user], [2, start]],
      streams: [
        [[3, word("one ")], [4, word("two ")]],
        [[4, word("two ")], [5, word("three")], [6, finished]],
      ],
    })
    setup()
    expect(await screen.findByText("one two three")).toBeInTheDocument()
    expect(afters).toEqual(["2", "4"])
  })

  it("shows a finished conversation without following anything", async () => {
    const afters = mockService({ running: false, stored: [[1, user], [2, start], [3, word("All done.")], [4, finished]] })
    setup()
    expect(await screen.findByText("All done.")).toBeInTheDocument()
    expect(afters).toEqual([])
  })

  it("says so in plain words when the service is not running", async () => {
    mockService({ running: false, stored: [], status: new Response(JSON.stringify({ ok: false, message: "The new agent isn't running. Start phoenix-agentkit (see deploy/agentkit/README.md)." }), { status: 503 }) })
    setup()
    expect(await screen.findByText(/isn't running/)).toBeInTheDocument()
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument()
  })

  it("says so in plain words when there is no API key", async () => {
    mockService({ running: false, stored: [], status: new Response(JSON.stringify({ running: true, key_present: false, message: "The new agent has no API key yet. See deploy/agentkit/README.md." }), { status: 200 }) })
    setup()
    expect(await screen.findByText(/no API key yet/)).toBeInTheDocument()
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument()
  })
})
