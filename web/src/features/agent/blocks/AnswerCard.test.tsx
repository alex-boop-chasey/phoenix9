import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AnswerCard, matchesWatch, type CardAnswer } from "@/features/agent/blocks/AnswerCard"
import { agentRoutes, failure, mockApi } from "@/test/mockApi"

class FakeEventSource {
  static last: FakeEventSource | null = null
  onopen: (() => void) | null = null
  onmessage: ((m: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  listeners: Record<string, ((m: MessageEvent) => void)[]> = {}
  constructor(public url: string) { FakeEventSource.last = this }
  addEventListener(type: string, fn: (m: MessageEvent) => void) { (this.listeners[type] ??= []).push(fn) }
  close() {}
  emit(type: string, data: object) {
    const m = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: "" })
    this.listeners[type]?.forEach((f) => f(m))
  }
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

const json = '{"v":1,"type":"gates"}'
const card = (over: Partial<CardAnswer> = {}): CardAnswer => ({
  type: "gates", title: "Open questions", data: [{ id: 1 }], inline: false,
  actions: [{ label: "Open", kind: "route", route: { to: "projects" } }],
  watch: { projects: ["demo"], runs: [], types: ["gate"] }, ...over,
})

function show(frozen = false) {
  return render(<QueryClientProvider client={new QueryClient()}>
    <AnswerCard json={json} resolved={{ type: "gates", query: {}, title: null }} frozen={frozen} />
  </QueryClientProvider>)
}

describe("matchesWatch", () => {
  it("matches by project, run and type prefix; empty means any", () => {
    const w = { projects: ["demo"], runs: [], types: ["gate"] }
    expect(matchesWatch(w, { type: "gate.opened", project: "demo" })).toBe(true)
    expect(matchesWatch(w, { type: "gate.opened", project: "other" })).toBe(false)
    expect(matchesWatch(w, { type: "run.started", project: "demo" })).toBe(false)
    expect(matchesWatch({ projects: [], runs: ["r1"], types: [] }, { type: "x", run: "r1" })).toBe(true)
    expect(matchesWatch({ projects: [], runs: [], types: [] }, { type: "command" })).toBe(false)
  })
})

describe("AnswerCard", () => {
  it("shows loading, then the title, body and buttons", async () => {
    const { calls } = mockApi({ ...agentRoutes(), "GET /api/cards": card() , "GET /api/events/recent": { events: [], next: 0 } })
    show()
    expect(screen.getByTestId("card-loading")).toBeTruthy()
    await waitFor(() => expect(screen.getByText("Open questions")).toBeTruthy())
    expect(screen.getByTestId("card-json")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Open" })).toBeTruthy()
    expect(calls.find((c) => c.path === "/api/cards")?.query).toMatchObject({ type: "gates", query: "{}" })
  })
  it("shows an error", async () => {
    mockApi({ ...agentRoutes(), "GET /api/cards": failure(400, "bad query"), "GET /api/events/recent": { events: [], next: 0 } })
    show()
    await waitFor(() => expect(screen.getByTestId("card-error").textContent).toContain("bad query"))
  })
  it("frozen cards have no buttons and fetch once", async () => {
    const { calls } = mockApi({ ...agentRoutes(), "GET /api/cards": card(), "GET /api/events/recent": { events: [], next: 0 } })
    show(true)
    await waitFor(() => expect(screen.getByText("Open questions")).toBeTruthy())
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull()
    expect(calls.filter((c) => c.path === "/api/cards")).toHaveLength(1)
  })
  it("refreshes once, debounced, when a matching event arrives", async () => {
    vi.stubGlobal("EventSource", FakeEventSource)
    const { calls } = mockApi({ ...agentRoutes(), "GET /api/cards": card() })
    show()
    await waitFor(() => expect(screen.getByText("Open questions")).toBeTruthy())
    const count = () => calls.filter((c) => c.path === "/api/cards").length
    expect(count()).toBe(1)
    vi.useFakeTimers()
    act(() => {
      FakeEventSource.last!.emit("run.started", { type: "run.started", project: "demo" })
      FakeEventSource.last!.emit("gate.opened", { type: "gate.opened", project: "demo" })
      FakeEventSource.last!.emit("gate.opened", { type: "gate.opened", project: "demo" })
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(400) })
    expect(count()).toBe(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(200) })
    vi.useRealTimers()
    await waitFor(() => expect(count()).toBe(2))
  })
  it("a button click goes through", async () => {
    mockApi({ ...agentRoutes(), "GET /api/cards": card(), "GET /api/events/recent": { events: [], next: 0 } })
    show()
    await waitFor(() => screen.getByRole("button", { name: "Open" }))
    fireEvent.click(screen.getByRole("button", { name: "Open" }))
    expect(window.location.hash).toBe("#/")
  })
})
