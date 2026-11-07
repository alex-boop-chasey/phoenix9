import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router"
import { useRef } from "react"

import { AgentPanel } from "@/features/agent/AgentPanel"
import { useAgentAlerts } from "@/features/agent/alerts"
import { agentKeys, type AgentMessages } from "@/features/agent/useAgent"
import { agentMessages, agentStatus, agentStatuses } from "@/test/fixtures"
import { agentRoutes, failure, mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

function Panel({ open = true }: { open?: boolean }) {
  const opener = useRef<HTMLButtonElement>(null)
  return <AgentPanel open={open} onClose={() => {}} opener={opener} />
}

beforeEach(() => window.localStorage.clear())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

test("shows skeleton rows while loading", () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": () => new Promise(() => {}) })
  renderWithProviders(<Panel />)
  expect(screen.getByTestId("agent-skeleton")).toBeInTheDocument()
})

test("ready: shows the conversation", async () => {
  mockApi(agentRoutes())
  renderWithProviders(<Panel />)
  expect(await screen.findByText("Check the build")).toBeInTheDocument()
  expect(screen.queryByTestId("agent-skeleton")).toBeNull()
})

test("asleep: card with Wake it, and the Claude app link only with app_url", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatus("asleep", { app_url: "https://claude.ai/code/x" }) })
  renderWithProviders(<Panel />)
  expect(await screen.findByText("The Phoenix agent is asleep")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Wake it" })).toBeInTheDocument()
  const link = screen.getAllByRole("link", { name: "Open in Claude app" })
  expect(link[0]).toHaveAttribute("href", "https://claude.ai/code/x")
})

test("asleep without app_url has no Claude app link", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses.asleep })
  renderWithProviders(<Panel />)
  await screen.findByText("The Phoenix agent is asleep")
  expect(screen.queryByRole("link", { name: "Open in Claude app" })).toBeNull()
})

test("send-only: says messages can't be read and the composer still works", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent/messages": failure(500, "unreadable") })
  renderWithProviders(<Panel />)
  expect(await screen.findByText(/messages can't be read/)).toBeInTheDocument()
  expect(screen.getByLabelText("Message")).not.toBeDisabled()
})

test("offline: a banner and the composer is disabled", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": failure(500, "down") })
  renderWithProviders(<Panel />)
  expect(await screen.findByRole("alert")).toHaveTextContent(/not answering/)
  expect(screen.getByLabelText("Message")).toBeDisabled()
})

test("wake: confirm, restart, then the status leaves asleep", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let state: "asleep" | "idle" = "asleep"
  const { calls } = mockApi({
    ...agentRoutes(),
    "GET /api/agent": () => agentStatus(state),
    "POST /api/agent/restart": () => { state = "idle"; return { restarted: true, unit: "claude-rc@home" } },
  })
  renderWithProviders(<Panel />)
  fireEvent.click(await screen.findByRole("button", { name: "Wake it" }))
  expect(calls.some((c) => c.path === "/api/agent/restart")).toBe(false)
  fireEvent.click((await screen.findAllByRole("button", { name: "Wake it" })).at(-1) as HTMLElement)
  await waitFor(() => expect(calls.find((c) => c.path === "/api/agent/restart")?.body).toEqual({ confirm: true }))
  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  await waitFor(() => expect(screen.queryByText("The Phoenix agent is asleep")).toBeNull())
})

test("wake: says so when the agent does not wake within 60 seconds", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses.asleep, "POST /api/agent/restart": { restarted: true, unit: "u" } })
  renderWithProviders(<Panel />)
  fireEvent.click(await screen.findByRole("button", { name: "Wake it" }))
  const confirm = (await screen.findAllByRole("button", { name: "Wake it" })).at(-1) as HTMLElement
  fireEvent.click(confirm)
  await screen.findByText("Waking the Phoenix agent…")
  await act(async () => { await vi.advanceTimersByTimeAsync(61_000) })
  expect(await screen.findByRole("alert")).toHaveTextContent(/did not wake/)
})

test("wake: a refused restart shows the reason", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses.asleep, "POST /api/agent/restart": failure(503, "No unit") })
  renderWithProviders(<Panel />)
  fireEvent.click(await screen.findByRole("button", { name: "Wake it" }))
  fireEvent.click((await screen.findAllByRole("button", { name: "Wake it" })).at(-1) as HTMLElement)
  expect(await screen.findByText("No unit")).toBeInTheDocument()
})

test("history: lists earlier conversations and opens one read-only, then goes back", async () => {
  const earlierData: AgentMessages = {
    session_id: "sess-2", unknown: 0, last_line: 1,
    items: [{ type: "user", line: 1, text: "Old question", origin: "panel", at: "2026-11-06T09:00:00Z" }],
  }
  const { calls } = mockApi({ ...agentRoutes(), "GET /api/agent/messages": (r: MockRequest) => (r.query.session ? earlierData : agentMessages) })
  renderWithProviders(<Panel />)
  await screen.findByText("Check the build")
  fireEvent.click(screen.getByRole("button", { name: "History" }))
  const items = await screen.findAllByRole("menuitem")
  expect(items).toHaveLength(1) // the current conversation is not listed
  expect(items[0]).toHaveTextContent("12 lines")
  fireEvent.click(items[0] as HTMLElement)
  expect(await screen.findByText("Old question")).toBeInTheDocument()
  expect(calls.some((c) => c.query.session === "sess-2")).toBe(true)
  expect(screen.queryByLabelText("Message")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Back to current" }))
  expect(await screen.findByLabelText("Message")).toBeInTheDocument()
  expect(screen.getByText("Check the build")).toBeInTheDocument()
})

function Bell({ open }: { open: boolean }) {
  const n = useAgentAlerts(open, () => {})
  return <span data-testid="unread">{n}</span>
}

function withClient(open: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (o: boolean) => (
    <QueryClientProvider client={client}><MemoryRouter><Bell open={o} /></MemoryRouter></QueryClientProvider>
  )
  const view = render(ui(open))
  return { client, rerender: (o: boolean) => view.rerender(ui(o)) }
}

const reply = (line: number): AgentMessages => ({
  ...agentMessages, last_line: line,
  items: [...agentMessages.items, { type: "agent", line, markdown: "Done", at: "2026-11-07T10:05:00Z" }],
})

test("a reply while closed toasts and counts; opening clears the count", async () => {
  mockApi(agentRoutes())
  const { client, rerender } = withClient(false)
  await waitFor(() => expect(client.getQueryData(agentKeys.messages("sess-1"))).toBeDefined())
  await screen.findByTestId("unread")
  expect(toast).not.toHaveBeenCalled() // the history that was already there is not news
  act(() => { client.setQueryData(agentKeys.messages("sess-1"), reply(9)) })
  await waitFor(() => expect(screen.getByTestId("unread")).toHaveTextContent("1"))
  expect(toast).toHaveBeenCalledWith("Phoenix agent replied", expect.anything())
  rerender(true)
  await waitFor(() => expect(screen.getByTestId("unread")).toHaveTextContent("0"))
})

test("a reply while open does not toast", async () => {
  mockApi(agentRoutes())
  const { client } = withClient(true)
  await waitFor(() => expect(client.getQueryData(agentKeys.messages("sess-1"))).toBeDefined())
  act(() => { client.setQueryData(agentKeys.messages("sess-1"), reply(9)) })
  await act(async () => {})
  expect(toast).not.toHaveBeenCalled()
  expect(screen.getByTestId("unread")).toHaveTextContent("0")
})
