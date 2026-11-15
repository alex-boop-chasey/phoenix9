// The save-attachment card: nothing is sent before Alex presses; Save posts the bytes to Phoenix as Alex; the agent
// hears only saved, cancelled or refused.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi } from "vitest"

import { ToolCall } from "./components"
import { referenceName } from "./savecard"

const BYTES = "%PDF-1.4 hello"
let sent: { url: string; method: string; body: string }[]
let existing: string[]

beforeEach(() => {
  sent = []
  existing = []
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    sent.push({ url: u, method: init?.method ?? "GET", body: String(init?.body ?? "") })
    if (u.includes("/attachments/a1")) return new Response(BYTES, { status: 200 })
    if (u.endsWith("/projects/demo/reference")) {
      return new Response(JSON.stringify({ ok: true, data: { files: existing.map((name) => ({ name, size: 1, modified: "", kind: "document" })), links: [] } }))
    }
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
  }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const file = (over: Record<string, unknown> = {}) => ({ name: "Design brief.pdf", mime: "application/pdf", size: BYTES.length, thread_id: "t1", ...over })
const draw = (f = file()) =>
  render(<ToolCall call={{ toolCallId: "s1", toolName: "offer_save_attachment", running: false, component: "SaveAttachmentCard",
    data: { attachment_id: "a1", project: "demo", file: f } }} />)
const answers = () => sent.filter((s) => s.url.includes("browser-results/s1")).map((s) => JSON.parse(s.body))
const uploads = () => sent.filter((s) => s.url.endsWith("/projects/demo/reference/files"))

test("no request is made before Alex presses", async () => {
  draw()
  expect(screen.getByText("Save into demo's reference documents?")).toBeInTheDocument()
  expect(screen.getByText(/Design brief\.pdf · 14 bytes/)).toBeInTheDocument()
  expect(screen.getByTestId("needs-you")).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(sent).toEqual([])
})

test("Save fetches the bytes, posts base64 to the reference route and reports saved", async () => {
  draw()
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(sent.some((s) => s.url.includes("agent-next/threads/t1/attachments/a1") && s.method === "GET")).toBe(true)
  expect(uploads()).toHaveLength(1)
  expect(JSON.parse(uploads()[0]!.body)).toEqual({ filename: "Design-brief.pdf", data_base64: btoa(BYTES) })
  expect(answers()[0]).toEqual({ result: { status: "saved" } })
  expect(screen.getByText("Saved into demo's reference documents.")).toBeInTheDocument()
  expect(screen.queryByTestId("needs-you")).toBeNull()
})

test("over 5 MB: Save is disabled with the reason, and the agent hears refused", async () => {
  draw(file({ size: 6 * 1024 * 1024 }))
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled()
  expect(screen.getByText("This file is too big for reference documents (at most 5 MB).")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "refused", reason: "too-big" } })
  expect(uploads()).toEqual([])
})

test("a type reference documents can't hold: Save is disabled with the reason", async () => {
  draw(file({ name: "build.log", mime: "text/plain" }))
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled()
  expect(screen.getByText("Files of this type can't be saved as reference documents.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()[0]).toEqual({ result: { status: "refused", reason: "wrong-type" } }))
})

test("a file of that name exists: Replace sends replace true", async () => {
  existing = ["Design-brief.pdf"]
  draw()
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await screen.findByText("demo already has a reference document called Design-brief.pdf. Replace it?")
  expect(uploads()).toEqual([])
  await userEvent.click(screen.getByRole("button", { name: "Replace" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(JSON.parse(uploads()[0]!.body)).toMatchObject({ filename: "Design-brief.pdf", replace: true })
  expect(answers()[0]).toEqual({ result: { status: "saved" } })
})

test("Cancel at the replace question reports cancelled and sends nothing", async () => {
  existing = ["Design-brief.pdf"]
  draw()
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "cancelled", reason: "exists" } })
  expect(uploads()).toEqual([])
})

test("Cancel reports cancelled and makes no other request", async () => {
  draw()
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "cancelled" } })
  expect(sent).toHaveLength(1)
  expect(screen.getByText("Cancelled.")).toBeInTheDocument()
})

test("Phoenix refusing the file reports refused with its plain words", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    sent.push({ url: u, method: init?.method ?? "GET", body: String(init?.body ?? "") })
    if (u.includes("/attachments/a1")) return new Response(BYTES)
    if (u.endsWith("/reference")) return new Response(JSON.stringify({ ok: true, data: { files: [], links: [] } }))
    if (u.endsWith("/reference/files")) return new Response(JSON.stringify({ ok: false, message: "A project can hold at most 40 reference files. Remove one first." }), { status: 400 })
    return new Response(JSON.stringify({ ok: true, data: {} }))
  }))
  draw()
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "refused", reason: "other" } })
  expect(screen.getByRole("alert")).toHaveTextContent("A project can hold at most 40 reference files.")
})

test("file names are cleaned like Phoenix does", () => {
  expect(referenceName("my notes v2.MD")).toEqual({ name: "my-notes-v2.md" })
  expect(referenceName("..\\a/..b..c.png")).toEqual({ name: "b.c.png" })
  expect(referenceName("run.sh")).toMatchObject({ reason: "wrong-type" })
  expect(referenceName("ünï.pdf")).toEqual({ name: "n.pdf" })
  expect(referenceName("ü.pdf")).toMatchObject({ reason: "wrong-type" })
})
