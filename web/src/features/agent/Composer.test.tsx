import { fireEvent, screen, waitFor } from "@testing-library/react"
import { useState } from "react"
import { toast } from "sonner"

import { Composer } from "@/features/agent/Composer"
import { ContextChip } from "@/features/agent/ContextChip"
import { forgetTold } from "@/features/agent/pageContext"
import { agentMessages, agentStatus } from "@/test/fixtures"
import { agentRoutes, failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))

function Both() {
  const [on, setOn] = useState(true)
  return (
    <>
      <ContextChip on={on} onChange={setOn} />
      <Composer contextOn={on} />
    </>
  )
}

const box = () => screen.getByLabelText("Message") as HTMLTextAreaElement
const type = (v: string) => fireEvent.change(box(), { target: { value: v } })
const sends = (calls: { method: string; path: string }[]) => calls.filter((c) => c.method === "POST" && c.path === "/api/agent/send")
const queuedThread = {
  ...agentMessages,
  items: [...agentMessages.items, { type: "queued" as const, line: 99, text: "wait", pending: true, at: "2026-11-07T10:01:00Z" }],
}

const calm = () => ({
  ...agentRoutes(),
  "GET /api/agent/messages": { ...agentMessages, items: agentMessages.items.filter((i) => i.type !== "queued") },
})

beforeEach(() => forgetTold())
afterEach(() => { vi.unstubAllGlobals(); vi.mocked(toast.error).mockClear() })

test("Enter sends and clears; Shift+Enter does not send", async () => {
  const { calls } = mockApi(calm())
  renderWithProviders(<Composer />)
  type("hello")
  fireEvent.keyDown(box(), { key: "Enter", shiftKey: true })
  expect(sends(calls)).toHaveLength(0)
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
  await waitFor(() => expect(box()).toHaveValue(""))
})

test("the send button sends, and is off for an empty box", async () => {
  const { calls } = mockApi(calm())
  renderWithProviders(<Composer />)
  const btn = screen.getByRole("button", { name: "Send" })
  expect(btn).toBeDisabled()
  expect(btn.querySelector('[data-icon="paper-plane"]')).not.toBeNull()
  type("hi")
  fireEvent.click(btn)
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
})

test("grows with its text but stops at 6 lines", () => {
  mockApi(calm())
  renderWithProviders(<Composer />)
  Object.defineProperty(box(), "scrollHeight", { configurable: true, value: 60 })
  type("a\nb\nc")
  expect(box().style.height).toBe("60px")
  Object.defineProperty(box(), "scrollHeight", { configurable: true, value: 900 })
  type("1\n2\n3\n4\n5\n6\n7\n8\n9")
  expect(box().style.height).toBe("136px")
})

test("a leading slash shows the commands hint", () => {
  mockApi(calm())
  renderWithProviders(<Composer />)
  type("hello /clear")
  expect(screen.queryByText(/Commands like \/clear/)).toBeNull()
  type("/clear")
  expect(screen.getByText("Commands like /clear don't work from here: use the Claude app.")).toBeInTheDocument()
})

test("asleep disables the box and shows why", async () => {
  mockApi({ ...calm(), "GET /api/agent": agentStatus("asleep") })
  renderWithProviders(<Composer />)
  expect(await screen.findByText(/agent is asleep/)).toBeInTheDocument()
  expect(box()).toBeDisabled()
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled()
})

test("a failed send shows the server's reason in a toast and keeps the text", async () => {
  mockApi({ ...calm(), "POST /api/agent/send": failure(503, "The inbox refused the message.") })
  renderWithProviders(<Composer />)
  type("hi")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("The inbox refused the message."))
  expect(box()).toHaveValue("hi")
})

test("shows a progress line while sending", async () => {
  let release: (v?: unknown) => void = () => {}
  const gate = new Promise((r) => { release = r })
  const api = mockApi(calm())
  vi.stubGlobal("fetch", (i: RequestInfo | URL, init?: RequestInit) => (init?.method === "POST" ? gate.then(() => api.fetch(i, init)) : api.fetch(i, init)))
  renderWithProviders(<Composer />)
  type("hi")
  fireEvent.keyDown(box(), { key: "Enter" })
  expect(await screen.findByRole("progressbar", { name: "Sending" })).toBeInTheDocument()
  release()
  await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull())
})

test("sends the page context, then only what changed", async () => {
  const { calls } = mockApi(calm())
  renderWithProviders(<Both />, { route: "/p/demo-site/build?run=r-1" })
  expect(screen.getByText(/Working in demo-site/)).toBeInTheDocument()
  expect(screen.getByText("r-1")).toHaveClass("mono")
  await screen.findByRole("switch")
  type("one")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
  expect(sends(calls)[0]).toMatchObject({ body: { text: "one", context: { page: "project/build", project: "demo-site", run: "r-1" } } })
  await waitFor(() => expect(box()).toHaveValue(""))
  await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull())
  type("two")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(2))
  expect(sends(calls)[1]).toMatchObject({ body: { text: "two" } })
  expect((sends(calls)[1] as unknown as { body: object }).body).not.toHaveProperty("context")
})

test("context is remembered per session id", async () => {
  let session = "sess-1"
  const { calls } = mockApi({ ...calm(), "GET /api/agent": () => agentStatus("idle", { session_id: session }) })
  const view = renderWithProviders(<Both />, { route: "/p/demo-site" })
  await waitFor(() => expect(calls.some((c) => c.path === "/api/agent")).toBe(true))
  type("a")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
  await waitFor(() => expect(box()).toHaveValue(""))
  await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull())
  view.unmount()
  session = "sess-2"
  renderWithProviders(<Both />, { route: "/p/demo-site" })
  await waitFor(() => expect(screen.getByTestId("agent-context").querySelector("[title]")).toHaveAttribute("title", expect.stringContaining("project: demo-site")))
  type("b")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(2))
  expect(sends(calls)[1]).toMatchObject({ body: { context: { project: "demo-site" } } })
})

test("the tooltip shows the exact line, and switching context off sends none", async () => {
  const { calls } = mockApi(calm())
  renderWithProviders(<Both />, { route: "/p/demo-site/build?run=r-1" })
  const tip = () => screen.getByTestId("agent-context").querySelector("[title]")
  expect(tip()).toHaveAttribute("title", "[Phoenix panel · page: project/build · project: demo-site · folder: /srv/projects/demo-site · run: r-1]")
  fireEvent.click(screen.getByRole("switch", { name: "Send page context" }))
  expect(tip()).toHaveAttribute("title", "Page context is off: nothing is sent.")
  type("plain")
  fireEvent.keyDown(box(), { key: "Enter" })
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
  expect((sends(calls)[0] as unknown as { body: object }).body).toEqual({ text: "plain" })
})

test("the chip says Working in Phoenix outside a project", () => {
  mockApi(calm())
  renderWithProviders(<Both />, { route: "/settings" })
  expect(screen.getByText(/Working in Phoenix/)).toBeInTheDocument()
})

test("a still-queued message asks first; Cancel keeps it, Send anyway sends", async () => {
  const { calls } = mockApi({ ...agentRoutes(), "GET /api/agent/messages": queuedThread })
  renderWithProviders(<Composer />)
  await waitFor(() => expect(calls.some((c) => c.path === "/api/agent/messages")).toBe(true))
  await new Promise((r) => setTimeout(r, 50))
  type("again")
  fireEvent.keyDown(box(), { key: "Enter" })
  expect(await screen.findByText("Still queued. Send anyway?")).toBeInTheDocument()
  expect(sends(calls)).toHaveLength(0)
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
  expect(screen.queryByText("Still queued. Send anyway?")).toBeNull()
  expect(box()).toHaveValue("again")
  fireEvent.keyDown(box(), { key: "Enter" })
  fireEvent.click(await screen.findByRole("button", { name: "Send anyway" }))
  await waitFor(() => expect(sends(calls)).toHaveLength(1))
})
