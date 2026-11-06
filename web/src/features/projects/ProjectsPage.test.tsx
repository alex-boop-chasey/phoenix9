/// <reference types="node" />
import { readFileSync } from "node:fs"

import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Route, Routes, useLocation } from "react-router"

import ImportPage from "@/pages/ImportPage"
import ProjectsPage from "@/pages/ProjectsPage"
import { switchState } from "@/lib/switcher"
import type { ImportCandidate, ProjectRow } from "@/lib/types"
import { projects } from "@/test/fixtures"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), loading: vi.fn(() => "t1") }))
vi.mock("sonner", () => ({ toast: toasts }))

afterEach(() => { vi.unstubAllGlobals(); Object.values(toasts).forEach((f) => f.mockClear()) })

/** A tiny stand-in for the server's search: same params, same reply shape. */
function search(rows: ProjectRow[], req: MockRequest) {
  if (!("attention" in req.query)) return rows
  const { q = "", status = "all", owner = "all", sort = "name", attention = "0" } = req.query
  const hit = rows.filter((r) =>
    (!q || `${r.name} ${r.description}`.toLowerCase().includes(q.toLowerCase())) &&
    (owner === "all" || (owner === "none" ? !r.repo : r.repo_owner === owner)))
  const counts = { all: hit.length, run: 0, fail: 0, idle: 0, need: 0 }
  hit.forEach((r) => { counts[switchState(r)]++ })
  const found = hit.filter((r) => status === "all" || switchState(r) === status)
    .sort((a, b) => (sort === "size" ? (b.size ?? 0) - (a.size ?? 0) : a.name.localeCompare(b.name)))
  const top = attention === "1" ? found.filter((r) => switchState(r) === "need") : []
  const rest = found.filter((r) => !top.includes(r))
  return { top, rest, total: found.length, counts }
}

function routes(rows: ProjectRow[] = projects, extra: Record<string, unknown> = {}) {
  return {
    "GET /api/projects": (req: MockRequest) => search(rows, req),
    "GET /api/gates": [],
    "GET /api/events/recent": { events: [], next: 0 },
    ...extra,
  }
}

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
        <Route path="/import" element={<ImportPage />} />
        <Route path="/p/:name" element={<div>project page</div>} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

const rowOf = (name: string) => document.querySelector(`[data-row="${name}"]`) as HTMLElement

test("title, lead line and Add project split button with two mini cards", async () => {
  mockApi(routes())
  renderPage()
  expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument()
  expect(screen.getByText("Every project on this server.")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Add project" })).toHaveAttribute("href", "/new")
  const chev = screen.getByRole("button", { name: "More ways to add a project" })
  expect(chev).toHaveAttribute("aria-expanded", "false")
  fireEvent.click(chev)
  expect(chev).toHaveAttribute("aria-expanded", "true")
  expect(screen.getByRole("menuitem", { name: /Create new/ })).toHaveAttribute("href", "/new")
  expect(screen.getByRole("menuitem", { name: /Import/ })).toHaveAttribute("href", "/import")
  fireEvent.keyDown(document, { key: "Escape" })
  expect(chev).toHaveAttribute("aria-expanded", "false")
})

test("each row shows name, path, status, repo and the three buttons", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  const demo = within(rowOf("demo-site"))
  expect(demo.getByText("/srv/projects/demo-site")).toBeInTheDocument()
  expect(demo.getByText("Needs you")).toBeInTheDocument()
  expect(demo.getByRole("link", { name: /rebirth-wd\/demo-site/ })).toHaveAttribute("href", "https://github.com/rebirth-wd/demo-site")
  expect(demo.getByRole("link", { name: /VS Code/ })).toHaveAttribute("href", "https://code.example.test/?folder=/srv/projects/demo-site")
  expect(demo.getByRole("link", { name: /Chat/ })).toHaveAttribute("href", "https://claude.ai/code/session_demo_site")
  expect(demo.getByRole("button", { name: /Remove/ })).toBeInTheDocument()
  expect(rowOf("demo-site").className).toContain("s-need")
  expect(rowOf("tiny-tool").className).toContain("s-run")
  expect(within(rowOf("tiny-tool")).getByText("Running task 2 of 4")).toBeInTheDocument()
  expect(within(rowOf("notes-only")).getByText("No repo")).toBeInTheDocument()
  expect(within(rowOf("notes-only")).getByText("Idle")).toBeInTheDocument()
})

test("the status pill sits right after the name and path, then the repo, then the buttons", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  const row = rowOf("demo-site")
  const order = [...row.querySelectorAll(".p-main, .p-status, .p-repo, .p-acts")].map((el) => el.className.split(" ")[0])
  expect(order).toEqual(["p-main", "p-status", "p-repo", "p-acts"])
  expect(within(row.querySelector(".p-status") as HTMLElement).getByText("Needs you")).toBeInTheDocument()
})

test("row columns are fixed widths with the repo left-aligned, so long repo names line up and have room", () => {
  const css = readFileSync(`${process.cwd()}/src/styles/projects.css`, "utf8")   // vitest runs in web/
  const wide = css.slice(css.indexOf("@container well (min-width:780px)"))
  expect(wide).toMatch(/\.p-meta\{[^}]*grid-template-columns:\s*\d+(\.\d+)?rem minmax\(0,\s*1fr\)/)
  expect(wide).not.toMatch(/\.p-meta\{[^}]*minmax\(\d+px,\s*auto\)/)
  expect(css).toMatch(/\.p-repo\{[^}]*justify-self:\s*start/)
  expect(css).toMatch(/\.p-repo\{[^}]*text-align:\s*left/)
})

test("clicking a row opens the project; clicking a button does not", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.click(within(rowOf("notes-only")).getByRole("button", { name: /Remove/ }))
  expect(screen.queryByText("project page")).toBeNull()
  fireEvent.click(rowOf("notes-only"))
  expect(await screen.findByText("project page")).toBeInTheDocument()
})

test("the Show dropdown filters by state and keeps the choice in the address", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  expect(screen.queryByRole("button", { name: /Needs my attention/ })).toBeNull()
  expect(screen.queryByLabelText("Owner")).toBeNull()
  const show = screen.getByLabelText("Show")
  expect(within(show).getAllByRole("option").map((o) => o.textContent))
    .toEqual(["All projects", "Needs you", "Running", "Failed", "Idle"])
  fireEvent.change(show, { target: { value: "run" } })
  expect(await screen.findByText("1 of 4 projects")).toBeInTheDocument()
  expect(rowOf("tiny-tool")).toBeTruthy()
  expect(rowOf("demo-site")).toBeNull()
  expect(screen.getByTestId("where").textContent).toBe("/?status=run")
})

test("Show: Needs you lists only the projects that need you", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.change(screen.getByLabelText("Show"), { target: { value: "need" } })
  expect(await screen.findByText("2 of 4 projects")).toBeInTheDocument()
  expect(screen.queryByText(/Everything else/)).toBeNull()
})

test("search and Sort work; Clear filters resets", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz" } })
  expect(await screen.findByText("No projects match")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))
  expect(await screen.findByText("4 projects")).toBeInTheDocument()
  const sort = screen.getByLabelText("Sort")
  expect(within(sort).getAllByRole("option").map((o) => o.textContent))
    .toEqual(["Name", "Last active", "Date created", "Date modified"])
  fireEvent.change(sort, { target: { value: "created" } })
  expect(screen.getByTestId("where").textContent).toContain("sort=created")
})

test("the / key focuses the search box", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.keyDown(document.body, { key: "/" })
  expect(screen.getByRole("searchbox")).toHaveFocus()
})

test("the filters are read from the address", async () => {
  mockApi(routes())
  renderPage("/?q=site")
  expect(await screen.findByText("1 of 4 projects")).toBeInTheDocument()
  expect(screen.getByRole("searchbox")).toHaveValue("site")
})

test("remove asks first, then calls the API and offers Import in a toast", async () => {
  const { calls } = mockApi(routes(projects, { "POST /api/projects/notes-only/remove": { name: "notes-only" } }))
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.click(within(rowOf("notes-only")).getByRole("button", { name: /Remove/ }))
  expect(await screen.findByText("Remove notes-only from Phoenix?")).toBeInTheDocument()
  expect(screen.getByText(/You can bring it back with Import/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: /Remove from Phoenix/ }))
  await waitFor(() => expect(toasts.success).toHaveBeenCalled())
  const call = calls.find((c) => c.path === "/api/projects/notes-only/remove")!
  expect(call.body).toEqual({ confirm: true })
  const [title, opts] = toasts.success.mock.calls[0] as unknown as [string, { action: { label: string; onClick: () => void } }]
  expect(title).toBe("notes-only removed from Phoenix")
  expect(opts.action.label).toBe("Import")
})

test("cancel leaves the project alone", async () => {
  const { calls } = mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.click(within(rowOf("tiny-tool")).getByRole("button", { name: /Remove/ }))
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
  expect(calls.some((c) => c.path.endsWith("/remove"))).toBe(false)
})

test("phoenix9 shows the can't-be-removed dialog and never calls the API", async () => {
  const { calls } = mockApi(routes())
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.click(within(rowOf("phoenix9")).getByRole("button", { name: /Remove/ }))
  expect(await screen.findByText("phoenix9 can't be removed")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Remove from Phoenix/ })).toBeNull()
  expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument()
  expect(calls.some((c) => c.path.endsWith("/remove"))).toBe(false)
})

test("a Chat that is off has no button", async () => {
  mockApi(routes(projects))
  renderPage()
  await screen.findByText("4 projects")
  expect(within(rowOf("notes-only")).queryByRole("button", { name: /Chat/ })).toBeNull()
})

test("a Chat that is on but has no link yet gets its link", async () => {
  const on: ProjectRow[] = projects.map((p) => (p.name === "notes-only" ? { ...p, chat: { state: "on" as const, kind: "none" as const, url: null } } : p))
  const { calls } = mockApi(routes(on, {
    "POST /api/projects/notes-only/chat/start": { project: "notes-only", already: false, chat: { state: "on", kind: "session", url: "https://claude.ai/code/s1" } },
  }))
  renderPage()
  await screen.findByText("4 projects")
  fireEvent.click(within(rowOf("notes-only")).getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(toasts.success).toHaveBeenCalledWith("Chat for notes-only is on", expect.anything()))
  expect(calls.some((c) => c.path === "/api/projects/notes-only/chat/start")).toBe(true)
})

test("no projects at all shows the empty state", async () => {
  mockApi(routes([]))
  renderPage()
  expect(await screen.findByText("No projects yet")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Create new project" })).toHaveAttribute("href", "/new")
})

test("api error shows plain error with retry", async () => {
  mockApi({ ...routes(), "GET /api/projects": () => { throw new Error("boom") } })
  renderPage()
  expect(await screen.findByRole("alert")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
})

const removed: ImportCandidate = { name: "old-site", path: "/srv/projects/old-site", repo: "rebirth-wd/old-site", removed_on: "2026-10-02", kind: "removed" }
const folder: ImportCandidate = { name: "side-quest", path: "/srv/projects/side-quest", repo: null, removed_on: null, kind: "folder" }

test("import page lists both groups with counts and imports one", async () => {
  const api = mockApi({
    "GET /api/import/candidates": [removed, folder],
    "POST /api/import": { name: "old-site", path: removed.path, repo: removed.repo, was_removed: true, added: [], chat: "on" },
  })
  renderWithProviders(<ImportPage />)
  expect(await screen.findByText("Removed earlier (1)")).toBeInTheDocument()
  expect(screen.getByText("Not in Phoenix yet (1)")).toBeInTheDocument()
  expect(screen.getByText("rebirth-wd/old-site · removed on 2 October")).toBeInTheDocument()
  expect(screen.getByText("No repo · not in Phoenix yet")).toBeInTheDocument()
  fireEvent.click(within(document.querySelector('[data-candidate="old-site"]') as HTMLElement).getByRole("button", { name: /Import/ }))
  await waitFor(() => expect(toasts.success).toHaveBeenCalledWith("old-site imported"))
  expect(api.calls.find((c) => c.path === "/api/import")!.body).toEqual({ target: "old-site" })
  await waitFor(() => expect(api.calls.filter((c) => c.path === "/api/import/candidates").length).toBeGreaterThan(1))
})

test("import page imports a folder typed by hand", async () => {
  const api = mockApi({
    "GET /api/import/candidates": [],
    "POST /api/import": { name: "mine", path: "/srv/projects/mine", repo: null, was_removed: false, added: [], chat: "on" },
  })
  renderWithProviders(<ImportPage />)
  await screen.findByText("Removed earlier (0)")
  const go = screen.getByRole("button", { name: /^Import$/ })
  expect(go).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Folder"), { target: { value: "/srv/projects/mine" } })
  fireEvent.click(go)
  await waitFor(() => expect(toasts.success).toHaveBeenCalledWith("mine imported"))
  expect(api.calls.find((c) => c.path === "/api/import")!.body).toEqual({ target: "/srv/projects/mine" })
})

test("import page: Choose a folder browses folders and fills the path box", async () => {
  const listing = (path = "") => path === "/srv/projects/side-quest"
    ? { path, root: "/srv/projects", parent: "/srv/projects", folders: [] }
    : { path: "/srv/projects", root: "/srv/projects", parent: null, folders: [{ name: "side-quest", path: "/srv/projects/side-quest" }] }
  const api = mockApi({
    "GET /api/import/candidates": [],
    "GET /api/folders": (req: MockRequest) => listing(req.query.path),
  })
  renderWithProviders(<ImportPage />)
  await screen.findByText("Removed earlier (0)")
  fireEvent.click(screen.getByRole("button", { name: "Choose a folder" }))
  const dialog = await screen.findByRole("dialog")
  expect(within(dialog).getByRole("button", { name: "Use this folder" })).toBeDisabled()
  fireEvent.click(await within(dialog).findByRole("button", { name: "side-quest" }))
  await waitFor(() => expect(within(dialog).getByTestId("folder-here")).toHaveTextContent("/srv/projects/side-quest"))
  expect(await within(dialog).findByText("No folders in here.")).toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole("button", { name: "Use this folder" }))
  await waitFor(() => expect(screen.getByLabelText("Folder")).toHaveValue("/srv/projects/side-quest"))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(api.calls.some((c) => c.path === "/api/folders" && !c.query.path)).toBe(true)
})
