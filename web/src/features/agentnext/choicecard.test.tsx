// The choice card: single and multiple picks, cancel, no second answer, bad data, and an index-only answer.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi } from "vitest"

import { ToolCall } from "./components"

const data = { question: "Which type?", multiple: false, options: [{ label: "Web app", hint: "Pages" }, { label: "API" }, { label: "CLI" }] }
let sent: { url: string; body: string }[]

beforeEach(() => {
  sent = []
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    sent.push({ url: String(url), body: String(init?.body ?? "") })
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
  }))
})
afterEach(() => vi.unstubAllGlobals())

const draw = (d: unknown) => render(<ToolCall call={{ toolCallId: "c1", toolName: "ask_choice", running: false, component: "ChoiceCard", data: d }} />)
const answers = () => sent.filter((s) => s.url.includes("/api/agent-next/browser-results/c1")).map((s) => JSON.parse(s.body))

test("single choice answers at once with the index only, and a second click is ignored", async () => {
  draw(data)
  await userEvent.click(screen.getByRole("button", { name: /API/ }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "picked", picked: [1] } })
  expect(screen.getByText(/You picked: API/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /CLI/ })).toBeNull()
  expect(answers()).toHaveLength(1)
})

test("multiple choice toggles chips and Done answers with the indexes", async () => {
  draw({ ...data, multiple: true })
  await userEvent.click(screen.getByRole("button", { name: /CLI/ }))
  await userEvent.click(screen.getByRole("button", { name: /Web app/ }))
  await userEvent.click(screen.getByRole("button", { name: /CLI/ }))
  await userEvent.click(screen.getByRole("button", { name: /CLI/ }))
  expect(answers()).toHaveLength(0)
  await userEvent.click(screen.getByRole("button", { name: "Done" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "picked", picked: [0, 2] } })
  expect(screen.queryByRole("button", { name: "Done" })).toBeNull()
})

test("Cancel answers cancelled and only once", async () => {
  draw(data)
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "cancelled" } })
  expect(screen.getByText("Cancelled.")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull()
})

test("malformed data shows the plain fallback line", () => {
  const many = Array.from({ length: 13 }, (_, i) => ({ label: `o${i}` }))
  for (const bad of [{ question: "q", options: [{ label: "a" }] }, { question: "q", options: [{ label: "a" }, {}] }, { question: "q", options: many }, null]) {
    const { unmount } = draw(bad)
    expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
    unmount()
  }
})

test("the posted body holds only status and indexes, never labels", async () => {
  draw(data)
  await userEvent.click(screen.getByRole("button", { name: /Web app/ }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  const body = sent[0]!.body
  expect(body).not.toContain("Web app")
  expect(body).not.toContain("Pages")
  expect(Object.keys(JSON.parse(body).result).sort()).toEqual(["picked", "status"])
})
