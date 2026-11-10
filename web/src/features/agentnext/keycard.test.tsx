// The key card: the typed value goes only to Phoenix's keys save, never to the agent service or the page.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi } from "vitest"

import { ToolCall } from "./components"
import { KeyInputCard } from "./keycard"

const SECRET = "sk-test-very-secret-123"
const ask = { project: "demo", name: "STRIPE_KEY", why: "To take payments." }
type Sent = { url: string; body: string }
let sent: Sent[]

beforeEach(() => {
  sent = []
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    sent.push({ url: String(url), body: String(init?.body ?? "") })
    const data = String(url).includes("/keys/save") ? [] : {}
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 })
  }))
})
afterEach(() => vi.unstubAllGlobals())

test("shows the project, key and reason as text, with a masked field", () => {
  render(<KeyInputCard ask={ask} callId="k1" />)
  expect(screen.getByText("demo")).toBeInTheDocument()
  expect(screen.getByText("STRIPE_KEY")).toBeInTheDocument()
  expect(screen.getByText(/To take payments/)).toBeInTheDocument()
  const input = screen.getByLabelText(/STRIPE_KEY/)
  expect(input).toHaveAttribute("type", "password")
  expect(input).toHaveAttribute("autocomplete", "off")
  expect(input).toHaveAttribute("spellcheck", "false")
})

test("Save posts the value only to keys save, then tells the agent just 'saved'", async () => {
  render(<ToolCall call={{ toolCallId: "k1", toolName: "ask_for_key", running: false, component: "KeyInputCard", data: ask }} />)
  await userEvent.type(screen.getByLabelText(/STRIPE_KEY/), SECRET)
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(sent.some((s) => s.url.includes("/api/agent-next/browser-results/k1"))).toBe(true))

  const save = sent.filter((s) => s.url.includes("/api/projects/demo/keys/save"))
  expect(save).toHaveLength(1)
  expect(JSON.parse(save[0]!.body)).toEqual({ rows: [{ name: "STRIPE_KEY", value: SECRET, secret: true }] })
  for (const s of sent.filter((x) => x.url.includes("/api/agent-next/"))) expect(s.body).not.toContain(SECRET)
  expect(JSON.parse(sent.find((s) => s.url.includes("browser-results"))!.body)).toEqual({ result: { status: "saved" } })
  expect(document.body.innerHTML).not.toContain(SECRET)
  expect(screen.queryByLabelText(/STRIPE_KEY/)).toBeNull()
})

test("Cancel saves nothing and answers 'cancelled'", async () => {
  render(<KeyInputCard ask={ask} callId="k2" />)
  await userEvent.type(screen.getByLabelText(/STRIPE_KEY/), SECRET)
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(sent).toHaveLength(1))
  expect(sent[0]!.url).toContain("/api/agent-next/browser-results/k2")
  expect(JSON.parse(sent[0]!.body)).toEqual({ result: { status: "cancelled" } })
  expect(sent[0]!.body).not.toContain(SECRET)
  expect(document.body.innerHTML).not.toContain(SECRET)
})
