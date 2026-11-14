// The Agent drawer: page context with each message, the chip, sending while it works, the open-agent event, same chat as the page.
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef } from "react"
import { MemoryRouter } from "react-router"

import { AppShell } from "@/components/AppShell"
import { info, projects } from "@/test/fixtures"
import { mockApi, raw, type MockRequest, type Route } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import { AgentDrawer, type DrawerAsk } from "./AgentDrawer"
import AgentNextPage from "./AgentNextPage"

type Ev = Record<string, unknown>
const enc = new TextEncoder()
const frame = (n: number, e: Ev) => `id: ${n}\ndata: ${JSON.stringify(e)}\n\n`
const said = (id: string, text: string): Ev => ({ type: "CUSTOM", name: "user_message", value: { id, text } })
const reply = (id: string, text: string): Ev[] => [
  { type: "TEXT_MESSAGE_START", messageId: id, role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: id, delta: text },
  { type: "TEXT_MESSAGE_END", messageId: id },
]
const started = (run: string): Ev => ({ type: "RUN_STARTED", threadId: "t1", runId: run })
const finished = (run: string): Ev => ({ type: "RUN_FINISHED", threadId: "t1", runId: run })

/** The stored chat t1: one question and its answer. */
const STORED: Ev[] = [started("r0"), said("u0", "Where is the doctor?"), ...reply("a0", "It is under Health."), finished("r0")]

/**
 * Fake agent service behind /api/agent-next/. Streams come from `streams` in order; a stream with `hold` stays open
 * until `release()` sends the held frames and ends it (a reply still being written). `runs` answers each POST .../runs in turn.
 */
function service(o: { extra?: Record<string, Route>; thread?: Ev[]; running?: () => boolean; storedNow?: () => Ev[]; streams?: { frames: [number, Ev][]; hold?: [number, Ev][] }[]; runs?: unknown[] } = {}) {
  let n = 0
  let r = 0
  let release = () => {}
  const posts: MockRequest[] = []
  const runAnswers = o.runs ?? [raw({ run_id: "r1", queued: false }, 202)]
  const stored = () => (o.storedNow ? o.storedNow() : o.thread ?? STORED).map((event, i) => ({ number: i + 1, event }))
  mockApi({
    ...o.extra,
    "GET /api/agent-next/status": raw({ running: true, key_present: true }),
    "GET /api/agent-next/threads": raw({ threads: [{ id: "t1", title: "Where is the doctor?", created: 1, last_used: 1700000000 }] }),
    "GET /api/agent-next/spend": raw({ month: "2026-11", used_share: 0.1, state: "plenty" }),
    "GET /api/agent-next/threads/t1": () => raw({ thread: { id: "t1" }, running: o.running?.() ?? false, events: stored() }),
    "GET /api/agent-next/threads/t9": raw({ thread: { id: "t9" }, running: false, events: [] }),
    "POST /api/agent-next/threads": (req: MockRequest) => { posts.push(req); return raw({ id: "t9" }, 201) },
    "POST /api/agent-next/threads/t1/runs": (req: MockRequest) => { posts.push(req); return runAnswers[Math.min(r++, runAnswers.length - 1)] },
    "POST /api/agent-next/threads/t9/runs": (req: MockRequest) => { posts.push(req); return runAnswers[Math.min(r++, runAnswers.length - 1)] },
    "GET /api/agent-next/threads/t1/stream": () => streamAnswer(),
    "GET /api/agent-next/threads/t9/stream": () => streamAnswer(),
  })
  function streamAnswer() {
    const s = (o.streams ?? [])[n++] ?? { frames: [] }
    return new Response(new ReadableStream({ start(c) {
      for (const [num, e] of s.frames) c.enqueue(enc.encode(frame(num, e)))
      const rest = s.hold
      if (rest) release = () => { for (const [num, e] of rest) c.enqueue(enc.encode(frame(num, e))); c.close() }
      else c.close()
    } }), { status: 200, headers: { "Content-Type": "text/event-stream" } })
  }
  return { posts, release: () => release() }
}

function Drawer({ ask }: { ask?: DrawerAsk }) {
  const opener = useRef<HTMLButtonElement>(null)
  return <AgentDrawer open onClose={() => {}} opener={opener} ask={ask} />
}

function setup(route = "/p/demo-site/build?run=20261110-0900", ask?: DrawerAsk) {
  return render(<MemoryRouter initialEntries={[route]}><Drawer ask={ask} /></MemoryRouter>)
}

const runPosts = (posts: MockRequest[]) => posts.filter((p) => p.path.endsWith("/runs")).map((p) => p.body as Record<string, unknown>)

beforeEach(() => localStorage.clear())
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

describe("the agent drawer", () => {
  it("says what the agent will be told and sends that context with the message", async () => {
    const svc = service({ streams: [{ frames: [[1, started("r1")], [2, said("u1", "what is this project?")], [3, finished("r1")]] }] })
    setup()
    expect(screen.getByTestId("agent-context")).toHaveTextContent("Looking at: demo-site, build 20261110-0900")
    await userEvent.type(screen.getByLabelText("Message"), "what is this project?")
    await userEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(runPosts(svc.posts)).toHaveLength(1))
    expect(runPosts(svc.posts)[0]).toEqual({
      message: "what is this project?", context: { page: "project/build", project: "demo-site", run: "20261110-0900" },
    })
  })

  it("names a top page in plain words and sends no run when none is open", async () => {
    service()
    setup("/settings")
    expect(screen.getByTestId("agent-context")).toHaveTextContent("Looking at: Phoenix settings")
  })

  it("keeps the message box usable while it works: a second message shows as Queued and is followed when it starts", async () => {
    localStorage.setItem("agent-next-thread", "t1")
    let phase = 0
    const svc = service({
      running: () => phase === 1,
      storedNow: () => (phase === 0 ? STORED : [...STORED, started("r1"), said("u1", "first"), ...reply("a1", "One."), finished("r1"), started("r2"), said("u2", "second")]),
      runs: [raw({ run_id: "r1", queued: false }, 202), raw({ run_id: "r2", queued: true }, 202)],
      streams: [
        { frames: [[7, started("r1")], [8, said("u1", "first")], [9, reply("a1", "One.")[0]!], [10, reply("a1", "One.")[1]!]], hold: [[11, reply("a1", "One.")[2]!], [12, finished("r1")]] },
        { frames: [[15, reply("a2", "Two.")[0]!], [16, reply("a2", "Two.")[1]!], [17, finished("r2")]] },
      ],
    })
    setup()
    expect(await screen.findByText("It is under Health.")).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Message"), "first{Enter}")
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Message"), "second{Enter}")
    const queued = await screen.findByTestId("agent-queued")
    expect(queued).toHaveTextContent("Queued")
    expect(queued).toHaveTextContent("second")
    expect(screen.getByLabelText("Message")).toHaveValue("")
    expect(runPosts(svc.posts).map((b) => b.message)).toEqual(["first", "second"])
    expect(runPosts(svc.posts)[1]).toHaveProperty("context")

    phase = 1
    await act(async () => {
      svc.release()
    })
    // the first reply ends; the queued message has started on the service and the drawer follows it
    expect(await screen.findByText("Two.")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId("agent-queued")).not.toBeInTheDocument())
    expect(screen.getByText("second", { selector: "p" })).toBeInTheDocument()
  })

  it("shows the service's plain words when it refuses a message", async () => {
    localStorage.setItem("agent-next-thread", "t1")
    service({ runs: [raw({ error: "This chat is waiting for your answer on a change. Approve or refuse it first." }, 409)] })
    setup()
    expect(await screen.findByText("It is under Health.")).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Message"), "hello{Enter}")
    expect(await screen.findByRole("alert")).toHaveTextContent("This chat is waiting for your answer on a change. Approve or refuse it first.")
  })

  it("shows the same conversation as the full page", async () => {
    localStorage.setItem("agent-next-thread", "t1")
    service()
    const drawer = setup()
    expect(await within(screen.getByLabelText("Phoenix agent panel")).findByText("It is under Health.")).toBeInTheDocument()
    drawer.unmount()
    render(<MemoryRouter initialEntries={["/agent-next"]}><AgentNextPage /></MemoryRouter>)
    expect(await screen.findByText("It is under Health.")).toBeInTheDocument()
  })

  it("remembers a new chat started in the drawer so the page opens it too", async () => {
    service({ streams: [{ frames: [[1, started("r1")], [2, finished("r1")]] }] })
    setup()
    await userEvent.type(screen.getByLabelText("Message"), "hello{Enter}")
    await waitFor(() => expect(localStorage.getItem("agent-next-thread")).toBe("t9"))
  })

  it("lists earlier conversations in the history menu and opens one", async () => {
    service()
    setup()
    await userEvent.click(screen.getByRole("button", { name: "History" }))
    await userEvent.click(await screen.findByRole("menuitem", { name: /Where is the doctor\?/ }))
    expect(await screen.findByText("It is under Health.")).toBeInTheDocument()
    expect(localStorage.getItem("agent-next-thread")).toBe("t1")
  })
})

describe("the open-agent event", () => {
  it("opens the drawer and sends the message it carries", async () => {
    const svc = service({
      streams: [{ frames: [[1, started("r1")], [2, finished("r1")]] }],
      extra: {
        "GET /api/info": info, "GET /api/projects": projects, "GET /api/gates": [], "GET /api/bell": { count: 0, items: [] },
        "GET /api/events/recent": { events: [], next: 0 },
      },
    })
    renderWithProviders(<AppShell>x</AppShell>, { route: "/p/demo-site/overview" })
    const panel = screen.getByLabelText("Phoenix agent panel", { selector: "aside" })
    expect(panel).not.toHaveClass("open")
    act(() => { window.dispatchEvent(new CustomEvent("phoenix:open-agent", { detail: { message: "Tell me about this project" } })) })
    expect(panel).toHaveClass("open")
    await waitFor(() => expect(runPosts(svc.posts)).toHaveLength(1))
    expect(runPosts(svc.posts)[0]).toEqual({ message: "Tell me about this project", context: { page: "project/overview", project: "demo-site" } })
  })
})
