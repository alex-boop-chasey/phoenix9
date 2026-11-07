import { fireEvent, screen, within } from "@testing-library/react"

import { AppShell } from "@/components/AppShell"
import { crumbsFor } from "@/components/Crumbs"
import { gate, info, projects } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const withUpdate = (over: Partial<typeof info.update>) => ({ ...info, update: { ...info.update, ...over } })

function setup(opts: { info?: unknown; gates?: unknown[]; route?: string; projects?: unknown[] } = {}) {
  mockApi({
    "GET /api/info": opts.info ?? info,
    "GET /api/projects": opts.projects ?? projects,
    "GET /api/gates": opts.gates ?? [],
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

test("switcher sorts needs-you, running, idle and highlights the current project", async () => {
  setup({ route: "/p/tiny-tool/overview" })
  await within(switcher()).findByText("demo-site")
  const names = within(switcher()).getAllByRole("link").map((a) => a.textContent)
  const order = names.filter((n) => /^(demo-site|phoenix9|tiny-tool|notes-only)/.test(n ?? "")).map((n) => n!.split(/Needs|Building|Idle|1 q/)[0])
  expect(order).toEqual(["demo-site", "phoenix9", "tiny-tool", "notes-only"])
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

test("bell shows the backend's needs-you count and links to the first project needing you", async () => {
  setup({ gates: [gate, { ...gate, id: "x.2", project: "phoenix9" }] })
  const bell = await screen.findByRole("link", { name: /Needs you: 2 questions waiting/ })
  expect(screen.getByTestId("bell-count")).toHaveTextContent("2")
  await vi.waitFor(() => expect(bell).toHaveAttribute("href", "/p/demo-site/overview"))
})

test("bell has no count when nothing needs you", async () => {
  setup({ projects: projects.map((p) => ({ ...p, needs_you: 0, questions: [], activity: "idle" })) })
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

test("Ctrl+. toggles the agent drawer", async () => {
  setup()
  const drawer = screen.getByLabelText("Phoenix Agent", { selector: "aside" })
  expect(drawer).not.toHaveClass("open")
  fireEvent.click(screen.getByRole("button", { name: "Open Phoenix Agent" }))
  expect(drawer).toHaveClass("open")
  expect(screen.getByText("Phoenix Agent (coming in phase 6)")).toBeInTheDocument()
  fireEvent.keyDown(document, { key: ".", ctrlKey: true })
  expect(drawer).not.toHaveClass("open")
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
