import { fireEvent, screen, within } from "@testing-library/react"

import { AppShell } from "@/components/AppShell"
import { crumbsFor } from "@/components/Crumbs"
import { info, projects } from "@/test/fixtures"
import { agentRoutes, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const withUpdate = (over: Partial<typeof info.update>) => ({ ...info, update: { ...info.update, ...over } })

function setup(opts: { info?: unknown; gates?: unknown[]; route?: string; projects?: unknown[]; bell?: unknown } = {}) {
  window.localStorage.clear()
  mockApi({
    ...agentRoutes(),
    "GET /api/info": opts.info ?? info,
    "GET /api/projects": opts.projects ?? projects,
    "GET /api/gates": opts.gates ?? [],
    "GET /api/bell": opts.bell ?? { count: 0, items: [] },
    "GET /api/events/recent": { events: [], next: 0 },
  })
  return renderWithProviders(<AppShell>x</AppShell>, { route: opts.route })
}

const switcher = () => screen.getByRole("navigation", { name: "Project switcher" })

test("shows version", async () => {
  setup()
  expect(await screen.findByText("0.9.0")).toBeInTheDocument()
})

test("shows the version label", async () => {
  setup({ info: { ...info, label: "v9.1" } })
  expect(await screen.findByText("v9.1")).toBeInTheDocument()
})

test("update pill hidden when no update is available", async () => {
  setup({ info: withUpdate({ supported: true, available: false }) })
  await screen.findByText("0.9.0")
  expect(screen.queryByText(/^Update v/)).toBeNull()
})

test("update pill hidden when unsupported", async () => {
  setup({ info: withUpdate({ supported: false, available: true }) })
  await screen.findByText("0.9.0")
  expect(screen.queryByText(/^Update v/)).toBeNull()
})

test("update pill links to the Updates tab", async () => {
  setup({ info: withUpdate({ supported: true, available: true, newest: "0.9.1" }) })
  const pill = await screen.findByText("Update v0.9.1")
  expect(pill.closest("a")).toHaveAttribute("href", "/settings?tab=updates")
})

test("settings link goes to /settings", async () => {
  setup()
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings")
})

test("switcher groups building, paused, then the rest and highlights the current project", async () => {
  setup({ route: "/p/tiny-tool/overview" })
  await within(switcher()).findByText("demo-site")
  const names = within(switcher()).getAllByRole("link").map((a) => a.textContent)
  const order = names.filter((n) => /^(demo-site|phoenix9|tiny-tool|notes-only)/.test(n ?? "")).map((n) => n!.split(/Needs|Building|Idle|1 q/)[0])
  expect(order).toEqual(["tiny-tool", "demo-site", "phoenix9", "notes-only"])
  const current = within(switcher()).getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "true")
  expect(current).toHaveLength(1)
  expect(current[0]).toHaveTextContent("tiny-tool")
})

test("switcher has See all, New project and Style reference links", async () => {
  setup()
  const nav = switcher()
  expect(within(nav).getByRole("link", { name: "See all" })).toHaveAttribute("href", "/")
  expect(within(nav).getByRole("link", { name: /New project/ })).toHaveAttribute("href", "/new")
  expect(within(nav).getByRole("link", { name: "Style reference" })).toHaveAttribute("href", "/styles")
})

const bellData = (n: number) => ({
  count: n,
  items: Array.from({ length: n }, (_, i) => ({
    id: `question:p${i}:q`, kind: "question", title: `p${i} needs an answer`, detail: "Waiting.",
    page: { to: `p/p${i}/overview`, params: {}, hash: `#/p/p${i}/overview`, label: "x" },
  })),
})

test("bell shows the API's count and opens a list of what needs you", async () => {
  setup({ bell: bellData(2) })
  const bell = await screen.findByRole("button", { name: /Needs you: 2 things waiting/ })
  expect(await screen.findByText("2", { selector: "[data-testid=bell-count]" })).toBeInTheDocument()
  expect(screen.queryByTestId("bell-list")).toBeNull()
  fireEvent.click(bell)
  expect(screen.getAllByTestId("bell-item")).toHaveLength(2)
  expect(screen.getAllByTestId("bell-item")[0]).toHaveAttribute("href", "/p/p0/overview")
})

test("bell has no count when nothing needs you", async () => {
  setup({ bell: bellData(0) })
  await screen.findByText("0.9.0")
  expect(screen.queryByTestId("bell-count")).toBeNull()
})

test("phone picker opens and closes", async () => {
  setup()
  const sheet = document.querySelector(".sheet") as HTMLElement
  expect(sheet).toHaveAttribute("aria-hidden", "true")
  fireEvent.click(screen.getByRole("button", { name: "Choose a project" }))
  expect(sheet).toHaveClass("open")
  fireEvent.click(screen.getByTestId("scrim"))
  expect(sheet).not.toHaveClass("open")
  fireEvent.click(screen.getByRole("button", { name: "Choose a project" }))
  fireEvent.keyDown(document, { key: "Escape" })
  expect(sheet).not.toHaveClass("open")
})

test("Ctrl+. toggles the Phoenix agent panel and the button opens it", async () => {
  setup()
  const panel = screen.getByLabelText("Phoenix agent panel", { selector: "aside" })
  expect(panel).not.toHaveClass("open")
  fireEvent.click(screen.getByRole("button", { name: "Phoenix agent" }))
  expect(panel).toHaveClass("open")
  fireEvent.keyDown(document, { key: ".", ctrlKey: true })
  expect(panel).not.toHaveClass("open")
  fireEvent.keyDown(document, { key: ".", ctrlKey: true })
  expect(panel).toHaveClass("open")
  fireEvent.keyDown(document, { key: "Escape" })
  expect(panel).not.toHaveClass("open")
})

test("the panel gives focus back to the header button", () => {
  setup()
  const btn = screen.getByRole("button", { name: "Phoenix agent" })
  fireEvent.click(btn)
  expect(screen.getByLabelText("Message")).toHaveFocus()
  fireEvent.keyDown(document, { key: "Escape" })
  expect(btn).toHaveFocus()
})

test("breadcrumbs show on the page", () => {
  setup({ route: "/p/demo-site/build" })
  const trail = screen.getByRole("navigation", { name: "Breadcrumb" })
  expect(trail).toHaveTextContent("Projects/demo-site/Build")
})

test("crumbs per route", () => {
  const labels = (p: string) => crumbsFor(p).map((c) => c.label)
  expect(labels("/")).toEqual(["Projects"])
  expect(labels("/p/demo-site")).toEqual(["Projects", "demo-site"])
  expect(labels("/p/demo-site/logs")).toEqual(["Projects", "demo-site", "Logs"])
  expect(labels("/settings")).toEqual(["Phoenix settings"])
  expect(labels("/styles")).toEqual(["Phoenix settings", "Style reference"])
  expect(labels("/new")).toEqual(["Projects", "New project"])
  expect(labels("/import")).toEqual(["Projects", "Import"])
  expect(crumbsFor("/p/demo-site/logs")[1]?.to).toBe("/p/demo-site/overview")
})

test("the sidebar's current project line has a Chat button with its dot", async () => {
  const rows = projects.map((p) => (p.name === "tiny-tool"
    ? { ...p, chat: { state: "sleeping", bridge_session_id: null, web_url: null, app_url: null, last_active: null } } : p))
  setup({ route: "/p/tiny-tool/overview", projects: rows })
  await within(switcher()).findByText("tiny-tool")
  expect(within(switcher()).getByRole("button", { name: /Chat/ })).toBeInTheDocument()
  expect(switcher().querySelector(".chatdot")).toHaveClass("chatdot-sleeping")
})

function stubWidth(phone: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: phone && q.includes("max-width: 719px"), media: q, addEventListener() {}, removeEventListener() {},
  }))
}

test("the scrim shows behind the panel on phone width only", () => {
  stubWidth(true)
  const first = setup()
  fireEvent.click(screen.getByRole("button", { name: "Phoenix agent" }))
  expect(screen.getByTestId("scrim")).toHaveClass("open")
  first.unmount()
  stubWidth(false)
  setup()
  fireEvent.click(screen.getByRole("button", { name: "Phoenix agent" }))
  expect(screen.getByTestId("scrim")).not.toHaveClass("open")
})

test("the open panel is remembered", () => {
  setup()
  fireEvent.click(screen.getByRole("button", { name: "Phoenix agent" }))
  const again = document.createElement("div")
  expect(again).toBeTruthy()
  expect(window.localStorage.getItem("phoenix.agent.open")).toBe("1")
})

test("only the main content scrolls: header and sidebar sit outside the page scroller", async () => {
  setup({ route: "/p/demo-site/overview" })
  const main = screen.getByRole("main")
  expect(main).toHaveAttribute("id", "page")
  expect(main).toHaveClass("well")
  const header = document.querySelector("header.top")!
  expect(header).not.toBeNull()
  expect(main.contains(header)).toBe(false)
  expect(main.contains(switcher())).toBe(false)
  expect(header.parentElement).toHaveClass("app")
  expect(main.contains(screen.getByText("x"))).toBe(true)
})

test("navigating scrolls the page scroller back to the top", async () => {
  setup()
  const main = screen.getByRole("main")
  main.scrollTop = 300
  fireEvent.click(screen.getByRole("link", { name: "Settings" }))
  expect(main.scrollTop).toBe(0)
})
