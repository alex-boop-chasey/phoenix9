import { fireEvent, screen, within } from "@testing-library/react"
import { Route, Routes, useLocation } from "react-router"

import ProjectPage from "@/pages/ProjectPage"
import { projects } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<div>home</div>} />
        <Route path="/p/:name/:tab" element={<ProjectPage />} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

function api(name = "demo-site") {
  mockApi({
    [`GET /api/projects/${name}`]: projects.find((p) => p.name === name),
    "GET /api/gates": [],
    [`GET /api/projects/${name}/runs`]: [],
    [`GET /api/projects/${name}/changelog`]: [],
    "GET /api/events/recent": { events: [], next: 0 },
  })
}

describe("ProjectPage", () => {
  it("four tabs present, with the waiting count on Overview", async () => {
    api()
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    const tabs = within(screen.getByRole("navigation", { name: "Project tabs" })).getAllByRole("link")
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview1", "Build", "Logs", "Settings"])
    expect(screen.getByLabelText("1 waiting for you")).toBeInTheDocument()
  })

  it("tab change updates the url", async () => {
    api()
    renderAt("/p/demo-site/overview")
    fireEvent.click(await screen.findByRole("link", { name: "Logs" }))
    expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/logs")
  })

  it("deep link opens the right tab", async () => {
    api()
    renderAt("/p/demo-site/settings")
    expect(await screen.findByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page")
  })

  it("unknown project shows not found", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ ok: false, message: "No such project." }), {
        status: 404, headers: { "Content-Type": "application/json" },
      }),
    )
    renderAt("/p/nope/overview")
    expect(await screen.findByText("No project called nope")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Back to projects" })).toHaveAttribute("href", "/")
  })

  it("header has Repo, VS Code, Chat and Start new build", async () => {
    api()
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    const dock = within(screen.getByRole("group", { name: "Open project" }))
    expect(dock.getByRole("link", { name: "Repo" })).toHaveAttribute("href", "https://github.com/rebirth-wd/demo-site")
    expect(dock.getByRole("link", { name: "VS Code" })).toHaveAttribute("href", projects[0]!.vscode_url)
    expect(dock.getByRole("link", { name: "VS Code" })).toHaveAttribute("target", "_blank")
    expect(dock.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "https://claude.ai/code/session_demo_site")
    expect(screen.getByRole("link", { name: "Start new build" })).toHaveAttribute("href", "/p/demo-site/build?new=1")
    expect(screen.getByText("/srv/projects/demo-site")).toBeInTheDocument()
  })

  it("no Start chat when the chat is off, and a missing repo is disabled", async () => {
    api("notes-only")
    renderAt("/p/notes-only/overview")
    await screen.findByRole("heading", { name: "notes-only" })
    const dock = within(screen.getByRole("group", { name: "Open project" }))
    expect(dock.queryByRole("button", { name: "Start chat" })).toBeNull()
    expect(dock.getByRole("button", { name: "Repo" })).toBeDisabled()
  })
})
