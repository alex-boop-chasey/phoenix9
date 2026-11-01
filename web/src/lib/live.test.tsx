import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"

import { useLiveEvents } from "@/lib/live"
import { mockApi } from "@/test/mockApi"

class FakeEventSource {
  static last: FakeEventSource | null = null
  onopen: (() => void) | null = null
  onmessage: ((m: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  listeners: Record<string, ((m: MessageEvent) => void)[]> = {}
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(type: string, data: object, id: string) {
    const m = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id })
    this.listeners[type]?.forEach((f) => f(m))
  }
}

function setup() {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test("uses EventSource when available", () => {
  vi.stubGlobal("EventSource", FakeEventSource)
  const { wrapper } = setup()
  const { result, unmount } = renderHook(() => useLiveEvents("demo-site"), { wrapper })
  expect(FakeEventSource.last?.url).toContain("api/events?project=demo-site")
  expect(result.current.mode).toBe("live")
  unmount()
  expect(FakeEventSource.last?.closed).toBe(true)
})

test("falls back to polling on error", async () => {
  vi.useFakeTimers()
  vi.stubGlobal("EventSource", FakeEventSource)
  const seen: number[] = []
  const { calls } = mockApi({
    "GET /api/events/recent": (req: { query: Record<string, string> }) =>
      req.query.after === undefined
        ? { events: [], next: 7 }
        : { events: [{ id: 8, ts: "", type: "run.started", project: "demo-site", run: "r", task: null, step: null, data: {} }], next: 8 },
  })
  const { wrapper } = setup()
  const { result } = renderHook(() => useLiveEvents("demo-site", (e) => seen.push(e.id)), { wrapper })
  await act(async () => {
    FakeEventSource.last!.onerror?.()
  })
  expect(FakeEventSource.last?.closed).toBe(true)
  expect(result.current.mode).toBe("polling")
  expect(calls[0]!.query.after).toBeUndefined()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000)
  })
  expect(calls[1]!.query.after).toBe("7")
  expect(seen).toEqual([8])
})

test("event invalidates matching queries", () => {
  vi.stubGlobal("EventSource", FakeEventSource)
  const { client, wrapper } = setup()
  client.setQueryData(["project", "demo-site"], { name: "demo-site" })
  client.setQueryData(["project", "other"], { name: "other" })
  renderHook(() => useLiveEvents(), { wrapper })
  act(() => {
    FakeEventSource.last!.emit("command", { type: "command", project: "demo-site" }, "1")
  })
  expect(client.getQueryState(["project", "demo-site"])?.isInvalidated).toBe(false)
  act(() => {
    FakeEventSource.last!.emit("run.started", { type: "run.started", project: "demo-site", run: "r1" }, "2")
  })
  expect(client.getQueryState(["project", "demo-site"])?.isInvalidated).toBe(true)
  expect(client.getQueryState(["project", "other"])?.isInvalidated).toBe(false)
})
