import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useLocation } from "react-router"
import { toast } from "sonner"

import { AppShell } from "@/components/AppShell"
import { info, projects } from "@/test/fixtures"
import { agentRoutes, failure, mockApi, type Route } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), info: vi.fn(), error: vi.fn() }) }))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.mocked(toast.error).mockClear()
})

const items = [
  { id: "question:demo:g1", kind: "question", title: "demo needs an answer: Which colour?", detail: "Waiting 2 hours.",
    page: { to: "p/demo/overview", params: { gate: "g1" }, hash: "#/p/demo/overview?gate=g1", label: "x" } },
  { id: "service:phoenix:x", kind: "service", title: "A service is not running", detail: "The notifier is stopped.",
    page: { to: "settings", params: {}, hash: "#/settings", label: "x" } },
]

/** Shows the current address so tests can see where a click went. */
function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

function setup(bell: unknown, extra: Record<string, Route> = {}) {
  window.localStorage.clear()
  return mockApi({
    ...agentRoutes(),
    "GET /api/info": info,
    "GET /api/projects": projects,
    "GET /api/gates": [],
    "GET /api/bell": bell,
    "GET /api/events/recent": { events: [], next: 0 },
    ...extra,
  })
}

function show(bell: unknown, extra: Record<string, Route> = {}) {
  const api = setup(bell, extra)
  const view = renderWithProviders(<AppShell><Where /></AppShell>)
  return { ...api, ...view }
}

test("the count is the API's count, not the projects' sum", async () => {
  show({ count: 7, items })
  expect(await screen.findByTestId("bell-count")).toHaveTextContent("7")
})

test("each item links to its page with title and detail", async () => {
  show({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  const links = screen.getAllByTestId("bell-item")
  expect(links[0]).toHaveAttribute("href", "/p/demo/overview?gate=g1")
  expect(links[0]).toHaveTextContent("Which colour?")
  expect(links[1]).toHaveAttribute("href", "/settings")
  expect(links[1]).toHaveTextContent("The notifier is stopped.")
})

test("an empty list says nothing needs you", async () => {
  show({ count: 0, items: [] })
  fireEvent.click(await screen.findByRole("button", { name: /nothing waiting/ }))
  expect(screen.getByText("Nothing needs you.")).toBeInTheDocument()
})

test("the phoenix:open-bell event opens it, Escape closes it", async () => {
  show({ count: 2, items })
  await screen.findByTestId("bell-count")
  act(() => { window.dispatchEvent(new Event("phoenix:open-bell")) })
  expect(screen.getByTestId("bell-list")).toBeInTheDocument()
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByTestId("bell-list")).toBeNull()
})

test("a click outside closes it", async () => {
  show({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  fireEvent.mouseDown(document.body)
  expect(screen.queryByTestId("bell-list")).toBeNull()
})

test("no dollar figure is rendered", async () => {
  const { container } = show({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  expect(container.textContent).not.toMatch(/\$\s?\d/)
})

const dated = [
  { ...items[0], since: "2026-11-13T15:42:00" },
  { ...items[1], since: "2026-11-09T09:05:00" },
  { id: "report:phoenix:2025-03-01", kind: "report", title: "Daily report for 2025-03-01", detail: "",
    since: "2025-03-01T20:00:00", page: { to: "projects", params: {}, hash: "#/", label: "x" } },
  { id: "suggestion:demo:x", kind: "suggestion", title: "Fill in empty keys", detail: "", since: "",
    page: { to: "projects", params: {}, hash: "#/", label: "x" } },
]

/** Bell routes that remember dismissals, like the server does. */
function liveBell(start: typeof items) {
  let bell = { count: start.length, items: start }
  return {
    "GET /api/bell": () => bell,
    "POST /api/bell/dismiss": (req: { body: unknown }) => {
      const id = (req.body as { id: string }).id
      bell = { count: bell.items.filter((i) => i.id !== id).length, items: bell.items.filter((i) => i.id !== id) }
      return bell
    },
    "POST /api/bell/dismiss-all": () => { bell = { count: 0, items: [] }; return bell },
  }
}

async function openBell() {
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
}

test("each row shows when it happened in local time, with the full date in its title", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-13T18:00:00") })
  show({ count: 4, items: dated })
  await openBell()
  const rows = screen.getAllByTestId("bell-row")
  expect(within(rows[0]!).getByTestId("bell-when")).toHaveTextContent(/^3:42 pm$/)
  expect(within(rows[0]!).getByTestId("bell-when")).toHaveAttribute("title", "Friday 13 November 2026, 3:42 pm")
  expect(within(rows[1]!).getByTestId("bell-when")).toHaveTextContent(/^9 Nov, 9:05 am$/)
  expect(within(rows[2]!).getByTestId("bell-when")).toHaveTextContent(/^1 Mar 2025, 8:00 pm$/)
  expect(within(rows[3]!).queryByTestId("bell-when")).toBeNull()
})

test("Dismiss removes the row at once, keeps the list open and sends the id", async () => {
  const { calls } = show({ count: 2, items }, liveBell(items))
  await openBell()
  fireEvent.click(screen.getByRole("button", { name: "Dismiss: demo needs an answer: Which colour?" }))
  await waitFor(() => expect(screen.getAllByTestId("bell-item")).toHaveLength(1))
  expect(screen.getByTestId("bell-list")).toBeInTheDocument()
  expect(screen.getByTestId("bell-count")).toHaveTextContent("1")
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/bell/dismiss")).toBe(true))
  expect(calls.find((c) => c.path === "/api/bell/dismiss")?.body).toEqual({ id: "question:demo:g1" })
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/)
})

test("clicking a row goes to its page, dismisses it and closes the list", async () => {
  const { calls } = show({ count: 2, items }, liveBell(items))
  await openBell()
  fireEvent.click(screen.getAllByTestId("bell-item")[1]!)
  expect(screen.getByTestId("where")).toHaveTextContent("/settings")
  expect(screen.queryByTestId("bell-list")).toBeNull()
  await waitFor(() => expect(screen.getByTestId("bell-count")).toHaveTextContent("1"))
  await waitFor(() => expect(calls.find((c) => c.path === "/api/bell/dismiss")?.body).toEqual({ id: "service:phoenix:x" }))
})

test("Dismiss all empties the list and the badge", async () => {
  const { calls } = show({ count: 2, items }, liveBell(items))
  await openBell()
  fireEvent.click(screen.getByRole("button", { name: "Dismiss all" }))
  expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument()
  expect(screen.queryByTestId("bell-count")).toBeNull()
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/bell/dismiss-all")).toBe(true))
  expect(screen.queryByRole("button", { name: "Dismiss all" })).toBeNull()
})

test("Dismiss all is only offered for two or more rows", async () => {
  show({ count: 1, items: [items[0]] })
  await openBell()
  expect(screen.queryByRole("button", { name: "Dismiss all" })).toBeNull()
})

test("a failed dismiss puts the row back and says so", async () => {
  show({ count: 2, items }, { "POST /api/bell/dismiss": failure(500, "Disk full.") })
  await openBell()
  fireEvent.click(screen.getByRole("button", { name: "Dismiss: A service is not running" }))
  await waitFor(() => expect(toast.error).toHaveBeenCalled())
  await waitFor(() => expect(screen.getAllByTestId("bell-item")).toHaveLength(2))
  expect(screen.getAllByTestId("bell-item")[1]).toHaveTextContent("A service is not running")
  expect(screen.getByTestId("bell-count")).toHaveTextContent("2")
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Disk full."))
})

test("the count follows the list as rows go", async () => {
  show({ count: 2, items }, liveBell(items))
  await openBell()
  expect(screen.getByTestId("bell-count")).toHaveTextContent("2")
  fireEvent.click(screen.getByRole("button", { name: /^Dismiss: demo/ }))
  await waitFor(() => expect(screen.getByTestId("bell-count")).toHaveTextContent("1"))
  fireEvent.click(screen.getByRole("button", { name: /^Dismiss: A service/ }))
  await waitFor(() => expect(screen.queryByTestId("bell-count")).toBeNull())
  expect(screen.getByText("Nothing needs you.")).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole("button", { name: "Needs you: nothing waiting" })).toBeInTheDocument())
})

test("Tab goes from a row to its Dismiss button", async () => {
  show({ count: 2, items })
  await openBell()
  const row = screen.getAllByTestId("bell-row")[0]!
  const order = Array.from(row.querySelectorAll("a, button"))
  expect(order[0]).toBe(screen.getAllByTestId("bell-item")[0])
  expect(order[1]).toHaveAccessibleName("Dismiss: demo needs an answer: Which colour?")
  expect(order[1]!.closest("a")).toBeNull()
})
