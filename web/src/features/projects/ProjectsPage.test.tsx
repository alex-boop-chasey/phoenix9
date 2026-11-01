import { fireEvent, screen, within } from "@testing-library/react"
import { Route, Routes, useLocation } from "react-router"

import { projects } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import ProjectsPage from "@/pages/ProjectsPage"

afterEach(() => vi.unstubAllGlobals())

const routes = (rows: unknown = projects) => ({
  "GET /api/projects": rows,
  "GET /api/gates": [],
  "GET /api/events/recent": { events: [], next: 0 },
})

function Where() {
  const loc = useLocation()
  return <div data-testid="where">{loc.pathname + loc.search}</div>
}

function renderPage(route = "/") {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/new" element={<div>new form</div>} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

function setWidth(width: number) {
  window.innerWidth = width
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width >= 768, media: query, addEventListener: () => {}, removeEventListener: () => {},
  }))
}

beforeEach(() => {
  setWidth(1280)
  // jsdom lacks these; the Radix Select needs them to open.
  Element.prototype.scrollIntoView = () => {}
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
})

function openOwner() {
  fireEvent.pointerDown(screen.getByRole("combobox", { name: "Owner" }), { button: 0, ctrlKey: false, pointerType: "mouse" })
}

const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr") as HTMLElement

test("shows every column for each project", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  for (const h of ["Project", "Path", "Repo", "Size", "Chat", "VS Code", "Status"]) {
    expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument()
  }
  const row = within(rowOf("demo-site"))
  expect(row.getByText("A small marketing site for a pretend bakery.")).toBeInTheDocument()
  expect(row.getByText("/srv/projects/demo-site")).toBeInTheDocument()
  expect(row.getByText("rebirth-wd/demo-site")).toBeInTheDocument()
  expect(row.getByText("5.0 MB")).toBeInTheDocument()
  expect(row.getByText("Open chat")).toBeInTheDocument()
  expect(row.getByText("Open")).toBeInTheDocument()
  expect(row.getByText("Chat on")).toBeInTheDocument()
})

test("name links to the project page", async () => {
  mockApi(routes())
  renderPage()
  expect(await screen.findByRole("link", { name: "tiny-tool" })).toHaveAttribute("href", "/p/tiny-tool")
})

test("repo, chat and vscode links have the right hrefs and open in a new tab", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  const row = within(rowOf("demo-site"))
  for (const [name, href] of [
    ["rebirth-wd/demo-site", "https://github.com/rebirth-wd/demo-site"],
    ["Open chat", "https://claude.ai/code/session_demo_site"],
    ["Open", "https://code.example.test/?folder=/srv/projects/demo-site"],
  ] as const) {
    const a = row.getByRole("link", { name })
    expect(a).toHaveAttribute("href", href)
    expect(a).toHaveAttribute("target", "_blank")
    expect(a).toHaveAttribute("rel", "noreferrer")
  }
  expect(within(rowOf("tiny-tool")).getByText("(project)")).toBeInTheDocument()
  expect(within(rowOf("notes-only")).getAllByText("—").length).toBeGreaterThanOrEqual(2)
})

test("size shows formatted bytes and a placeholder when unknown", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  expect(within(rowOf("demo-site")).getByText("5.0 MB")).toBeInTheDocument()
  expect(within(rowOf("tiny-tool")).getByTitle("Being measured")).toHaveTextContent("…")
})

test("status shows running task x of y", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  expect(within(rowOf("tiny-tool")).getByText("Running task 2 of 4")).toBeInTheDocument()
  expect(within(rowOf("notes-only")).getByText("Idle")).toBeInTheDocument()
  expect(within(rowOf("tiny-tool")).getByText("Chat off")).toBeInTheDocument()
})

test("needs-you badge shown and sorted first", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  const names = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("link")[0]!.textContent)
  expect(names).toEqual(["demo-site", "phoenix9", "tiny-tool", "notes-only"])
  const badge = within(rowOf("demo-site")).getByText("Needs you")
  expect(badge.closest("a")).toHaveAttribute("href", "/p/demo-site/overview")
  expect(within(rowOf("tiny-tool")).queryByText("Needs you")).toBeNull()
})

test("search filters by name and description", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  const box = screen.getByPlaceholderText("Search projects")
  fireEvent.change(box, { target: { value: "BAKERY" } })
  expect(screen.getByText("1 of 4 projects")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "demo-site" })).toBeInTheDocument()
  fireEvent.change(box, { target: { value: "tiny" } })
  expect(screen.getByRole("link", { name: "tiny-tool" })).toBeInTheDocument()
  fireEvent.change(box, { target: { value: "zzz" } })
  expect(screen.getByText("No projects match")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))
  expect(await screen.findByText("4 of 4 projects")).toBeInTheDocument()
})

test("owner filter lists owners present plus No repo", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  openOwner()
  const options = (await screen.findAllByRole("option")).map((o) => o.textContent)
  expect(options).toEqual(["All owners", "alex-boop-chasey", "rebirth-wd", "No repo"])
})

test("owner filter kept in the url", async () => {
  mockApi(routes())
  renderPage("/?owner=rebirth-wd&q=site")
  expect(await screen.findByText("1 of 4 projects")).toBeInTheDocument()
  expect(screen.getByPlaceholderText("Search projects")).toHaveValue("site")
  openOwner()
  fireEvent.click(await screen.findByRole("option", { name: "No repo" }))
  expect(await screen.findByText("No projects match")).toBeInTheDocument()
  expect(screen.getByTestId("where").textContent).toBe("/?owner=__none__&q=site")
})

test("create button goes to #/new", async () => {
  mockApi(routes())
  renderPage()
  const link = await screen.findByRole("link", { name: "Create new project" })
  expect(link).toHaveAttribute("href", "/new")
  fireEvent.click(link)
  expect(await screen.findByText("new form")).toBeInTheDocument()
})

test("empty list shows empty state", async () => {
  mockApi(routes([]))
  renderPage()
  expect(await screen.findByText("No projects yet")).toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: "Create new project" })).toHaveLength(2)
})

test("api error shows plain error with retry", async () => {
  mockApi({ ...routes(), "GET /api/projects": () => { throw new Error("boom") } })
  renderPage()
  expect(await screen.findByRole("alert")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
  expect(screen.queryByText(/at .*\.tsx?/)).toBeNull()
})

test("phone layout renders cards", async () => {
  setWidth(390)
  mockApi(routes())
  renderPage()
  await screen.findByText("4 of 4 projects")
  expect(screen.queryByRole("table")).toBeNull()
  const cards = screen.getAllByRole("listitem")
  expect(cards).toHaveLength(4)
  const first = within(cards[0]!)
  expect(first.getByText("demo-site")).toBeInTheDocument()
  expect(first.getByText("Needs you")).toBeInTheDocument()
  expect(first.getByRole("link", { name: "VS Code" })).toBeInTheDocument()
  expect(first.getByText("/srv/projects/demo-site")).toBeInTheDocument()
})
