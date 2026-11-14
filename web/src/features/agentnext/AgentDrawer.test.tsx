// The Agent drawer: page context with each message, the chip, sending while it works, the open-agent event, same chat as the page,
// the "not answering" card with Restart, and the unread dot on the Agent button.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef } from "react"
import { MemoryRouter } from "react-router"

import { AppShell } from "@/components/AppShell"
import { info, projects } from "@/test/fixtures"
import { failure, mockApi, raw, type MockRequest, type Route } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import { AgentDrawer, type DrawerAsk } from "./AgentDrawer"
import AgentNextPage from "./AgentNextPage"
import { RESTART_LIMIT_MS, RESTART_LOOK_MS } from "./NotAnswering"

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
    ...o.extra,
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

const NOT_RUNNING = "The new agent isn't running."
const DOWN = raw({ ok: false, message: NOT_RUNNING }, 503)
const UP = raw({ running: true, key_present: true })

/** The drawer inside the query provider (the Restart button posts through it). */
function setupWithProviders() {
  return renderWithProviders(<Drawer />, { route: "/settings" })
}

/** A service that is down until `up()`; the restart route answers with `restart`. */
function downService(restart: Route = { service: "agent", restarted: true, waited: false, doctor: [] }) {
  let isUp = false
  const svc = service({
    extra: {
      "GET /api/agent-next/status": () => (isUp ? UP : DOWN),
      "POST /api/service/agent/restart": (req: MockRequest) => { svc.posts.push(req); return typeof restart === "function" ? restart(req) : restart },
    },
  })
  return { ...svc, up: () => { isUp = true }, restarts: () => svc.posts.filter((p) => p.path === "/api/service/agent/restart") }
}

describe("when the agent is not answering", () => {
  afterEach(() => vi.useRealTimers())

  it.each([
    ["not running", DOWN, "The agent is not running", NOT_RUNNING, true],
    ["not set up", raw({ ok: false, message: "The agent isn't set up yet: its token file can't be read." }, 503),
      "The agent is not set up yet", "The agent isn't set up yet: its token file can't be read.", false],
    ["without a key", raw({ running: true, key_present: false, message: "The new agent has no API key yet." }),
      "The agent has no API key yet", "The new agent has no API key yet.", false],
  ])("shows a card saying it is %s", async (_name, status, heading, words, restart) => {
    service({ extra: { "GET /api/agent-next/status": status } })
    setupWithProviders()
    const card = await screen.findByTestId("agent-not-answering")
    expect(within(card).getByRole("heading", { name: heading })).toBeInTheDocument()
    expect(card).toHaveTextContent(words)
    expect(within(card).queryByRole("button", { name: "Restart the agent" }) !== null).toBe(restart)
    expect(screen.queryByLabelText("Message")).toBeNull()
  })

  it("asks before restarting, posts once, then says the agent is back and shows the conversation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const svc = downService()
    setupWithProviders()
    fireEvent.click(await screen.findByRole("button", { name: "Restart the agent" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog).toHaveTextContent("Restart the agent?")
    expect(svc.restarts()).toHaveLength(0)
    fireEvent.click(within(dialog).getByRole("button", { name: "Restart" }))
    await waitFor(() => expect(svc.restarts()).toHaveLength(1))
    expect(svc.restarts()[0]!.body).toEqual({ yes: true })
    expect(await screen.findByText("Restarting the agent…")).toBeInTheDocument()
    svc.up()
    await act(async () => { await vi.advanceTimersByTimeAsync(RESTART_LOOK_MS) })
    expect(await screen.findByText("The agent is back.")).toBeInTheDocument()
    expect(await screen.findByLabelText("Message")).toBeInTheDocument()
    expect(screen.queryByTestId("agent-not-answering")).toBeNull()
    expect(svc.restarts()).toHaveLength(1)
  })

  it("says plainly when the agent does not come back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const svc = downService()
    setupWithProviders()
    fireEvent.click(await screen.findByRole("button", { name: "Restart the agent" }))
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Restart" }))
    await waitFor(() => expect(svc.restarts()).toHaveLength(1))
    await act(async () => { await vi.advanceTimersByTimeAsync(RESTART_LIMIT_MS + RESTART_LOOK_MS) })
    expect(await screen.findByRole("alert")).toHaveTextContent("The agent did not come back within 30 seconds.")
    expect(screen.getByRole("button", { name: "Restart the agent" })).toBeEnabled()
    expect(svc.restarts()).toHaveLength(1)
  })

  it("shows Phoenix's words when the restart is refused", async () => {
    const svc = downService(failure(400, "The agent is not set up yet."))
    setupWithProviders()
    fireEvent.click(await screen.findByRole("button", { name: "Restart the agent" }))
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Restart" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("The restart did not work: The agent is not set up yet.")
    expect(svc.restarts()).toHaveLength(1)
  })
})

describe("the unread dot on the Agent button", () => {
  const shell = {
    "GET /api/info": info, "GET /api/projects": projects, "GET /api/gates": [], "GET /api/bell": { count: 0, items: [] },
    "GET /api/events/recent": { events: [], next: 0 },
  }

  /** Open the drawer, send a message whose reply is held, then close the drawer. */
  async function sendThenClose() {
    renderWithProviders(<AppShell>x</AppShell>, { route: "/settings" })
    const btn = screen.getByRole("button", { name: "Phoenix agent" })
    fireEvent.click(btn)
    await userEvent.type(await screen.findByLabelText("Message"), "hello{Enter}")
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.getByLabelText("Phoenix agent panel", { selector: "aside" })).not.toHaveClass("open")
    return btn
  }

  it("shows when a reply finishes while the drawer is closed and clears when it opens", async () => {
    const svc = service({ extra: shell, streams: [{ frames: [[1, started("r1")], [2, said("u1", "hello")]], hold: [[3, finished("r1")]] }] })
    const btn = await sendThenClose()
    expect(screen.queryByTestId("agent-unread")).toBeNull()
    await act(async () => { svc.release() })
    const dot = await screen.findByTestId("agent-unread")
    expect(dot).toHaveAttribute("aria-label", "New from the agent")
    fireEvent.click(btn)
    expect(screen.queryByTestId("agent-unread")).toBeNull()
  })

  it("shows when an approval starts waiting while the drawer is closed", async () => {
    const ask: Ev = { type: "CUSTOM", name: "approval_request", value: { approvalId: "a1", toolName: "notifications-set", input: {} } }
    const svc = service({ extra: shell, streams: [{ frames: [[1, started("r1")], [2, said("u1", "hello")]], hold: [[3, ask]] }] })
    await sendThenClose()
    await act(async () => { svc.release() })
    expect(await screen.findByTestId("agent-unread")).toBeInTheDocument()
  })

  it("stays off when the reply finishes with the drawer open", async () => {
    const svc = service({ extra: shell, streams: [{ frames: [[1, started("r1")], [2, finished("r1")]] }] })
    renderWithProviders(<AppShell>x</AppShell>, { route: "/settings" })
    fireEvent.click(screen.getByRole("button", { name: "Phoenix agent" }))
    await userEvent.type(await screen.findByLabelText("Message"), "hello{Enter}")
    await waitFor(() => expect(runPosts(svc.posts)).toHaveLength(1))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop" })).toBeNull())
    expect(screen.queryByTestId("agent-unread")).toBeNull()
  })
})
