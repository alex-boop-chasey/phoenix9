import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { createElement, type ReactNode } from "react"

import { agentMessages, agentStatus, agentStatuses } from "@/test/fixtures"
import { FakeEventSource } from "@/test/fakeEventSource"
import { agentRoutes, failure, mockApi } from "@/test/mockApi"
import { useAgentMessages, useAgentStatus, useAgentStream, useSendToAgent, type AgentMessages } from "./useAgent"

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
  return { client, wrapper }
}

/** Messages and the stream together, as the panel uses them. */
function useBoth(enabled: boolean) {
  useAgentStream(enabled)
  return useAgentMessages()
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal("EventSource", FakeEventSource)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const lines = (d?: AgentMessages) => d?.items.map((i) => i.line)

test("status is fetched", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses.working })
  const { wrapper } = setup()
  const { result } = renderHook(() => useAgentStatus(), { wrapper })
  await waitFor(() => expect(result.current.data?.state).toBe("working"))
})

test("messages stay cached across unmount and remount", async () => {
  const { calls } = mockApi(agentRoutes())
  const { wrapper } = setup()
  const first = renderHook(() => useAgentMessages(), { wrapper })
  await waitFor(() => expect(first.result.current.data?.items).toHaveLength(8))
  first.unmount()
  const second = renderHook(() => useAgentMessages(), { wrapper })
  expect(second.result.current.data?.items).toHaveLength(8)
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/agent").length).toBeGreaterThan(0))
  expect(calls.filter((c) => c.path === "/api/agent/messages")).toHaveLength(1)
})

test("stream items are appended without duplicates", async () => {
  mockApi(agentRoutes())
  const { wrapper } = setup()
  const { result } = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(FakeEventSource.last).not.toBeNull())
  expect(FakeEventSource.last!.url).toContain("api/agent/stream?after=8")
  act(() => {
    FakeEventSource.last!.emit("item", { type: "agent", line: 9, markdown: "Done", at: "t" }, "sess-1:9")
    FakeEventSource.last!.emit("item", { type: "agent", line: 9, markdown: "Done", at: "t" }, "sess-1:9")
  })
  await waitFor(() => expect(lines(result.current.data)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]))
})

test("an update frame patches the action by id", async () => {
  mockApi(agentRoutes())
  const { wrapper } = setup()
  const { result } = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(FakeEventSource.last).not.toBeNull())
  act(() => {
    FakeEventSource.last!.emit("update", { type: "update", id: "tool-1", line: 3, status: "ok", excerpt: "12 passed" })
  })
  await waitFor(() =>
    expect(result.current.data?.items.find((i) => i.type === "action")).toMatchObject({ status: "ok", excerpt: "12 passed" }),
  )
})

test("a session frame starts a fresh list with a divider", async () => {
  mockApi(agentRoutes())
  const { wrapper } = setup()
  const { result } = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(result.current.data?.items).toHaveLength(8))
  act(() => {
    FakeEventSource.last!.emit("session", { session_id: "sess-2" })
  })
  await waitFor(() => expect(result.current.data?.session_id).toBe("sess-2"))
  expect(result.current.data?.items).toEqual([{ type: "session", line: 0, session_id: "sess-2" }])
  await waitFor(() => expect(FakeEventSource.last!.url).toContain("after=0"))
  act(() => {
    FakeEventSource.last!.emit("item", { type: "user", line: 1, text: "hi", origin: "panel", at: "t" }, "sess-2:1")
  })
  await waitFor(() => expect(result.current.data?.items.map((i) => i.type)).toEqual(["session", "user"]))
})

test("a changed session while closed does not append to the old list", async () => {
  let status = agentStatuses.idle
  const { calls } = mockApi({
    ...agentRoutes(),
    "GET /api/agent": () => status,
    "GET /api/agent/messages": () =>
      status.session_id === "sess-2"
        ? { items: [{ type: "user", line: 1, text: "new", origin: "app", at: "t" }], unknown: 0, last_line: 1, session_id: "sess-2" }
        : agentMessages,
  })
  const { client, wrapper } = setup()
  const first = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(first.result.current.data?.items).toHaveLength(8))
  first.unmount()
  status = agentStatus("idle", { session_id: "sess-2" })
  await client.invalidateQueries({ queryKey: ["agent", "status"] })
  FakeEventSource.reset()
  const second = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(second.result.current.data?.session_id).toBe("sess-2"))
  expect(lines(second.result.current.data)).toEqual([1])
  await waitFor(() => expect(FakeEventSource.last?.url).toContain("after=1"))
  expect(FakeEventSource.all.every((s) => !s.url.includes("after=8"))).toBe(true)
  expect(client.getQueryData<AgentMessages>(["agent", "messages", "sess-1"])?.items).toHaveLength(8)
  expect(calls.some((c) => c.path === "/api/agent/messages")).toBe(true)
})

test("after a stream error it polls every 4 s", async () => {
  mockApi({
    ...agentRoutes(),
    "GET /api/agent/messages": (req: { query: Record<string, string> }) =>
      req.query.after === "8"
        ? { items: [{ type: "agent", line: 9, markdown: "later", at: "t" }], unknown: 0, last_line: 9, session_id: "sess-1" }
        : { ...agentMessages, items: agentMessages.items.filter((i) => i.type !== "action") },
  })
  const { wrapper } = setup()
  const { result } = renderHook(() => useBoth(true), { wrapper })
  await waitFor(() => expect(FakeEventSource.last).not.toBeNull())
  await waitFor(() => expect(result.current.data).toBeDefined())
  vi.useFakeTimers()
  act(() => FakeEventSource.last!.fail())
  expect(FakeEventSource.last!.closed).toBe(true)
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4100)
  })
  expect(lines(result.current.data)).toContain(9)
})

test("send posts the text and context with the api headers", async () => {
  const { calls } = mockApi(agentRoutes())
  const { wrapper } = setup()
  const { result } = renderHook(() => useSendToAgent(), { wrapper })
  await act(async () => {
    await result.current.mutateAsync({ text: "hello", context: { page: "projects", project: "demo-site" } })
  })
  const post = calls.find((c) => c.method === "POST")!
  expect(post.path).toBe("/api/agent/send")
  expect(post.body).toEqual({ text: "hello", context: { page: "projects", project: "demo-site" } })
  expect(post.headers["X-Phoenix"]).toBe("1")
})

test("send errors carry the server's reason", async () => {
  mockApi({ ...agentRoutes(), "POST /api/agent/send": failure(503, "The agent is asleep.") })
  const { wrapper } = setup()
  const { result } = renderHook(() => useSendToAgent(), { wrapper })
  await act(async () => {
    await result.current.mutateAsync({ text: "hi" }).catch(() => undefined)
  })
  await waitFor(() => expect(result.current.error?.message).toBe("The agent is asleep."))
})
