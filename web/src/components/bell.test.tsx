import { act, fireEvent, screen } from "@testing-library/react"

import { AppShell } from "@/components/AppShell"
import { info, projects } from "@/test/fixtures"
import { agentRoutes, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const items = [
  { id: "question:demo:g1", kind: "question", title: "demo needs an answer: Which colour?", detail: "Waiting 2 hours.",
    page: { to: "p/demo/overview", params: { gate: "g1" }, hash: "#/p/demo/overview?gate=g1", label: "x" } },
  { id: "service:phoenix:x", kind: "service", title: "A service is not running", detail: "The notifier is stopped.",
    page: { to: "settings", params: {}, hash: "#/settings", label: "x" } },
]

function setup(bell: unknown) {
  window.localStorage.clear()
  mockApi({
    ...agentRoutes(),
    "GET /api/info": info,
    "GET /api/projects": projects,
    "GET /api/gates": [],
    "GET /api/bell": bell,
    "GET /api/events/recent": { events: [], next: 0 },
  })
  return renderWithProviders(<AppShell>x</AppShell>)
}

test("the count is the API's count, not the projects' sum", async () => {
  setup({ count: 7, items })
  expect(await screen.findByTestId("bell-count")).toHaveTextContent("7")
})

test("each item links to its page with title and detail", async () => {
  setup({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  const links = screen.getAllByTestId("bell-item")
  expect(links[0]).toHaveAttribute("href", "/p/demo/overview?gate=g1")
  expect(links[0]).toHaveTextContent("Which colour?")
  expect(links[1]).toHaveAttribute("href", "/settings")
  expect(links[1]).toHaveTextContent("The notifier is stopped.")
})

test("an empty list says nothing needs you", async () => {
  setup({ count: 0, items: [] })
  fireEvent.click(await screen.findByRole("button", { name: /nothing waiting/ }))
  expect(screen.getByText("Nothing needs you.")).toBeInTheDocument()
})

test("the phoenix:open-bell event opens it, Escape closes it", async () => {
  setup({ count: 2, items })
  await screen.findByTestId("bell-count")
  act(() => { window.dispatchEvent(new Event("phoenix:open-bell")) })
  expect(screen.getByTestId("bell-list")).toBeInTheDocument()
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByTestId("bell-list")).toBeNull()
})

test("a click outside closes it", async () => {
  setup({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  fireEvent.mouseDown(document.body)
  expect(screen.queryByTestId("bell-list")).toBeNull()
})

test("no dollar figure is rendered", async () => {
  const { container } = setup({ count: 2, items })
  fireEvent.click(await screen.findByRole("button", { name: /Needs you/ }))
  expect(container.textContent).not.toMatch(/\$\s?\d/)
})
