// The flow card: active, done and cancelled flows, the Cancel message, bad data, and a replay showing one current card.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"

import AgentNextPage from "./AgentNextPage"
import { COMPONENTS } from "./components"

const data = (status: string, step: number, extra: Record<string, unknown> = {}) =>
  ({ flow: "f1", status, step, steps: 4, label: `label${step}`, values: { name: "shop", type: "web" }, ...extra })
const draw = (d: unknown, onSend?: (m: string) => void) => render(<>{COMPONENTS.FlowCard!({ data: d, tool: "flow", onSend })}</>)

describe("FlowCard", () => {
  it("shows an active flow with its facts and a Cancel button that sends the fixed message", async () => {
    const sent: string[] = []
    draw(data("active", 2), (m) => sent.push(m))
    expect(screen.getByText("Step 2 of 4: label2")).toBeInTheDocument()
    expect(screen.getByText("name: shop")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Cancel this" }))
    expect(sent).toEqual(["Cancel this and stop."])
  })
  it("shows done and cancelled flows without the button", () => {
    const a = draw(data("done", 4))
    expect(screen.getByText("Finished")).toBeInTheDocument()
    expect(screen.queryByRole("button")).toBeNull()
    a.unmount()
    draw(data("cancelled", 2))
    expect(screen.getByText("Cancelled")).toBeInTheDocument()
    expect(screen.queryByRole("button")).toBeNull()
  })
  it("leaves out facts named like a secret", () => {
    draw(data("active", 1, { values: { api_key: "x", name: "shop" } }))
    expect(screen.queryByText(/api_key/)).toBeNull()
    expect(screen.getByText("name: shop")).toBeInTheDocument()
  })
  it("shows nothing for malformed data", () => {
    for (const bad of [null, "x", { flow: "f", status: "weird", step: 1, steps: 2, label: "a" }, data("active", 9), data("active", 1, { values: { a: { b: 1 } } })]) {
      const { container, unmount } = draw(bad)
      expect(container).toBeEmptyDOMElement()
      unmount()
    }
  })
})

describe("replaying a flow", () => {
  it("shows one current card and older steps as single lines", async () => {
    const card = (n: number, status: string, step: number) => [n, { type: "CUSTOM", name: "component", value: { toolCallId: `c${n}`, component: "FlowCard", data: data(status, step) } }]
    const events = [[1, { type: "CUSTOM", name: "user_message", value: { id: "u1", text: "New project" } }], card(2, "active", 1), card(3, "active", 2), card(4, "active", 3)]
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost/").pathname.replace(/^.*agent-next\//, "")
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
      if (path === "status") return json({ running: true, key_present: true, pack: "phoenix", model: "m" })
      if (path === "threads") return json({ threads: [{ id: "t1", title: "New project", created: 1, last_used: 1 }] })
      if (path === "spend") return json({ month: "2026-11", used_share: 0.1, state: "plenty" })
      if (path === "threads/t1") return json({ thread: { id: "t1" }, running: false, events: events.map(([number, event]) => ({ number, event })) })
      return json({})
    }))
    localStorage.setItem("agent-next-thread", "t1")
    render(<MemoryRouter initialEntries={["/agent-next"]}><AgentNextPage /></MemoryRouter>)
    await waitFor(() => expect(screen.getAllByTestId("flow-card")).toHaveLength(1))
    expect(screen.getByText("Step 3 of 4: label3")).toBeInTheDocument()
    expect(screen.getAllByTestId("flow-line")).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: "Cancel this" })).toHaveLength(1)
    vi.unstubAllGlobals()
    localStorage.clear()
  })
})
