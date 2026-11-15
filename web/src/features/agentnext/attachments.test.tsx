// Files in the agent's message box: the paperclip, paste, drop, chips, sending files (also queued) and thumbnails
// in sent and reloaded messages.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef } from "react"
import { MemoryRouter } from "react-router"

import { mockApi, raw, type MockRequest, type Route } from "@/test/mockApi"
import { AgentDrawer } from "./AgentDrawer"
import { MAX_FILE } from "./attach"

type Ev = Record<string, unknown>
const enc = new TextEncoder()
const frame = (n: number, e: Ev) => `id: ${n}\ndata: ${JSON.stringify(e)}\n\n`
const started = (run: string): Ev => ({ type: "RUN_STARTED", threadId: "t1", runId: run })
const finished = (run: string): Ev => ({ type: "RUN_FINISHED", threadId: "t1", runId: run })
const SHOT = { id: "a1", name: "shot.png", mime: "image/png", size: 2048 }
const PDF = { id: "a2", name: "plan.pdf", mime: "application/pdf", size: 4096 }

/** Fake agent service: new chats get t9; each upload answers with the next of `uploads`. */
function service(o: { stored?: Ev[]; spend?: string; uploads?: unknown[]; streams?: { frames: [number, Ev][]; hold?: [number, Ev][] }[]; runs?: unknown[] } = {}) {
  const posts: MockRequest[] = []
  let u = 0
  let n = 0
  let r = 0
  let release = () => {}
  const uploads = o.uploads ?? [raw(SHOT, 201)]
  const runs = o.runs ?? [raw({ run_id: "r1", queued: false }, 202)]
  const record = (answer: () => unknown) => (req: MockRequest) => { posts.push(req); return answer() }
  const stream = () => {
    const s = (o.streams ?? [])[n++] ?? { frames: [] }
    return new Response(new ReadableStream({ start(c) {
      for (const [num, e] of s.frames) c.enqueue(enc.encode(frame(num, e)))
      if (s.hold) release = () => { for (const [num, e] of s.hold!) c.enqueue(enc.encode(frame(num, e))); c.close() }
      else c.close()
    } }), { status: 200, headers: { "Content-Type": "text/event-stream" } })
  }
  const routes: Record<string, Route> = {
    "GET /api/agent-next/status": raw({ running: true, key_present: true }),
    "GET /api/agent-next/threads": raw({ threads: [{ id: "t1", title: "Earlier", created: 1, last_used: 1700000000 }] }),
    "GET /api/agent-next/spend": raw({ month: "2026-11", used_share: 0.85, state: o.spend ?? "plenty" }),
    "GET /api/agent-next/threads/t1": raw({ thread: { id: "t1" }, running: false, events: (o.stored ?? []).map((event, i) => ({ number: i + 1, event })) }),
    "GET /api/agent-next/threads/t9": raw({ thread: { id: "t9" }, running: false, events: [] }),
    "POST /api/agent-next/threads": record(() => raw({ id: "t9" }, 201)),
    "GET /api/agent-next/threads/t1/stream": stream,
    "GET /api/agent-next/threads/t9/stream": stream,
  }
  for (const t of ["t1", "t9"]) {
    routes[`POST /api/agent-next/threads/${t}/attachments`] = record(() => uploads[Math.min(u++, uploads.length - 1)])
    routes[`POST /api/agent-next/threads/${t}/runs`] = record(() => runs[Math.min(r++, runs.length - 1)])
  }
  mockApi(routes)
  return { posts, release: () => release() }
}

function Drawer() {
  const opener = useRef<HTMLButtonElement>(null)
  return <AgentDrawer open onClose={() => {}} opener={opener} />
}

const setup = () => render(<MemoryRouter initialEntries={["/"]}><Drawer /></MemoryRouter>)
const png = (name = "shot.png", size = 2048) => new File([new Uint8Array(size)], name, { type: "image/png" })
const uploadsOf = (posts: MockRequest[]) => posts.filter((p) => p.path.endsWith("/attachments")).map((p) => p.body as Record<string, unknown>)
const runsOf = (posts: MockRequest[]) => posts.filter((p) => p.path.endsWith("/runs")).map((p) => p.body as Record<string, unknown>)
const attached = () => screen.getByRole("list", { name: "Attached files" })

beforeEach(() => localStorage.clear())
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

describe("attaching files", () => {
  it("has a paperclip left of the text box that opens a file input with the right accept list", async () => {
    service()
    setup()
    const clip = await screen.findByRole("button", { name: "Attach files" })
    expect(clip.querySelector('[data-icon="paperclip"]')).not.toBeNull()
    const box = screen.getByLabelText("Message")
    expect(clip.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(clip.closest(".ag-field")).toContainElement(box)
    const input = screen.getByTestId("attach-input") as HTMLInputElement
    expect(input.type).toBe("file")
    expect(input.multiple).toBe(true)
    expect(input.accept).toBe("image/*,application/pdf,.txt,.md,.csv,.json,.yaml,.yml,.toml,.log")
    const opened = vi.spyOn(input, "click")
    await userEvent.click(clip)
    expect(opened).toHaveBeenCalled()
  })

  it("shows a picked file as a chip, uploads it at once into a new chat and shows it ready", async () => {
    const svc = service()
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    const chip = within(attached()).getByText("shot.png").closest("li")!
    await waitFor(() => expect(chip).toHaveAttribute("data-state", "ready"))
    expect(chip).toHaveTextContent("2 KB")
    expect(within(chip).getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument()
    expect(svc.posts[0]!.path).toBe("/api/agent-next/threads")
    const body = uploadsOf(svc.posts)[0]!
    expect(svc.posts[1]!.path).toBe("/api/agent-next/threads/t9/attachments")
    expect(body.name).toBe("shot.png")
    expect(body.mime).toBe("image/png")
    expect(typeof body.data_base64).toBe("string")
    expect(atob(body.data_base64 as string)).toHaveLength(2048)
  })

  it("shows Uploading… until the service answers", async () => {
    let answer: (r: Response) => void = () => {}
    service()
    const inner = globalThis.fetch
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/attachments") ? new Promise<Response>((done) => { answer = done }) : inner(input, init))
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    expect(await within(attached()).findByText("Uploading…")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled()
    await act(async () => answer(new Response(JSON.stringify(SHOT), { status: 201 })))
    await waitFor(() => expect(within(attached()).queryByText("Uploading…")).not.toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled()
  })

  it("refuses a too-big file in one plain line and does not post it", async () => {
    const svc = service()
    setup()
    const big = new File([new Uint8Array(MAX_FILE + 1)], "huge.png", { type: "image/png" })
    fireEvent.change(await screen.findByTestId("attach-input"), { target: { files: [big] } })
    expect(await screen.findByTestId("file-refused")).toHaveTextContent("That file is too big to attach (at most 10 MB).")
    expect(screen.queryByRole("list", { name: "Attached files" })).not.toBeInTheDocument()
    expect(uploadsOf(svc.posts)).toEqual([])
  })

  it("shows the service's refusal in one line and drops the chip", async () => {
    service({ uploads: [raw({ error: "That file looks like it contains a secret (a key, token or password), so it was not attached." }, 400)] })
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), new File(["hello"], "notes.txt", { type: "text/plain" }))
    expect(await screen.findByTestId("file-refused")).toHaveTextContent("contains a secret")
    await waitFor(() => expect(screen.queryByRole("list", { name: "Attached files" })).not.toBeInTheDocument())
  })

  it("allows at most 5 files with one message", async () => {
    const svc = service()
    setup()
    const files = [1, 2, 3, 4, 5, 6].map((i) => png(`s${i}.png`))
    fireEvent.change(await screen.findByTestId("attach-input"), { target: { files } })
    expect(await screen.findByTestId("file-refused")).toHaveTextContent("At most 5 files can go with one message.")
    expect(within(attached()).getAllByRole("listitem")).toHaveLength(5)
    await waitFor(() => expect(uploadsOf(svc.posts)).toHaveLength(5))
  })

  it("attaches a pasted image", async () => {
    const svc = service()
    setup()
    fireEvent.paste(await screen.findByLabelText("Message"), { clipboardData: { files: [png("pasted.png")], types: ["Files"] } })
    expect(await within(attached()).findByText("pasted.png")).toBeInTheDocument()
    await waitFor(() => expect(uploadsOf(svc.posts)).toHaveLength(1))
    expect(uploadsOf(svc.posts)[0]!.name).toBe("pasted.png")
  })

  it("attaches a file dropped on the conversation, with a quiet outline while dragging", async () => {
    service({ uploads: [raw(PDF, 201)] })
    setup()
    const conv = await screen.findByTestId("agent-conversation")
    const pdf = new File(["%PDF-1.4"], "plan.pdf", { type: "application/pdf" })
    fireEvent.dragEnter(conv, { dataTransfer: { files: [pdf], types: ["Files"] } })
    expect(conv).toHaveClass("ag-drop")
    fireEvent.drop(conv, { dataTransfer: { files: [pdf], types: ["Files"] } })
    expect(conv).not.toHaveClass("ag-drop")
    const chip = (await within(attached()).findByText("plan.pdf")).closest("li")!
    expect(chip.querySelector('[data-icon="file-text"]')).not.toBeNull()
  })

  it("removes a chip with its x", async () => {
    service()
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    await userEvent.click(await screen.findByRole("button", { name: "Remove shot.png" }))
    expect(screen.queryByRole("list", { name: "Attached files" })).not.toBeInTheDocument()
  })

  it("sends a file with no words: Send is enabled, the body has the ids and empty text, and the bubble shows the thumbnail", async () => {
    const svc = service({ streams: [{ frames: [[1, started("r1")], [2, finished("r1")]] }] })
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    await waitFor(() => expect(within(attached()).getByText("shot.png").closest("li")).toHaveAttribute("data-state", "ready"))
    await userEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(runsOf(svc.posts)).toHaveLength(1))
    expect(runsOf(svc.posts)[0]).toEqual({ message: "", context: { page: "projects" }, attachments: ["a1"] })
    expect(screen.queryByRole("list", { name: "Attached files" })).not.toBeInTheDocument()
    const img = await screen.findByRole("img", { name: "shot.png" })
    expect(img.getAttribute("src")).toMatch(/\/api\/agent-next\/threads\/t9\/attachments\/a1$/)
    expect(img).toHaveAttribute("loading", "lazy")
  })

  it("queues a message with files while the agent works, carrying the ids", async () => {
    localStorage.setItem("agent-next-thread", "t1")
    const svc = service({
      runs: [raw({ run_id: "r1", queued: false }, 202), raw({ run_id: "r2", queued: true }, 202)],
      streams: [{ frames: [[7, started("r1")]], hold: [[9, finished("r1")]] }],
    })
    setup()
    await userEvent.type(await screen.findByLabelText("Message"), "first{Enter}")
    await screen.findByRole("button", { name: "Stop" })
    await userEvent.upload(screen.getByTestId("attach-input"), png())
    await waitFor(() => expect(within(attached()).getByText("shot.png").closest("li")).toHaveAttribute("data-state", "ready"))
    await userEvent.type(screen.getByLabelText("Message"), "and this{Enter}")
    expect(await screen.findByTestId("agent-queued")).toHaveTextContent("and this")
    expect(screen.getByTestId("agent-queued")).toHaveTextContent("shot.png")
    expect(runsOf(svc.posts)[1]).toMatchObject({ message: "and this", attachments: ["a1"] })
    expect(runsOf(svc.posts)[0]).not.toHaveProperty("attachments")
    await act(async () => svc.release())
  })

  it("says quietly that files use more of the allowance when it is low", async () => {
    service({ spend: "low" })
    setup()
    await screen.findByTestId("allowance")
    expect(screen.queryByTestId("files-allowance")).not.toBeInTheDocument()
    await userEvent.upload(screen.getByTestId("attach-input"), png())
    expect(await screen.findByTestId("files-allowance")).toHaveTextContent("Files use more of this month's allowance")
  })

  it("shows no allowance line for files while there is plenty left", async () => {
    service()
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    await within(attached()).findByText("shot.png")
    expect(screen.queryByTestId("files-allowance")).not.toBeInTheDocument()
  })
})

describe("on a phone", () => {
  it("keeps the field with its chips at the bottom, outside the scrolling chat (above the keyboard)", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("max-width: 719px"), media: q, addEventListener() {}, removeEventListener() {},
      addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false,
    }))
    service()
    setup()
    await userEvent.upload(await screen.findByTestId("attach-input"), png())
    const field = attached().closest(".ag-field")!
    expect(field).toContainElement(screen.getByLabelText("Message"))
    expect(field).toContainElement(screen.getByRole("button", { name: "Attach files" }))
    expect(field.closest(".ag-comp")).not.toBeNull()
    expect(document.querySelector(".ag-scroll")).not.toContainElement(field as HTMLElement)
  })
})

describe("a reloaded conversation", () => {
  it("shows the thumbnails and file chips from the stored message", async () => {
    localStorage.setItem("agent-next-thread", "t1")
    service({ stored: [started("r0"), { type: "CUSTOM", name: "user_message", value: { id: "u0", text: "What is this?", attachments: [SHOT, PDF] } }, finished("r0")] })
    setup()
    const img = await screen.findByRole("img", { name: "shot.png" })
    expect(img.getAttribute("src")).toMatch(/\/api\/agent-next\/threads\/t1\/attachments\/a1$/)
    expect(img).toHaveAttribute("loading", "lazy")
    const bubble = img.closest("[data-role=user]")!
    expect(bubble).toHaveTextContent("What is this?")
    const link = within(bubble as HTMLElement).getByRole("link", { name: "plan.pdf" })
    expect(link.getAttribute("href")).toMatch(/\/threads\/t1\/attachments\/a2$/)
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
  })
})
