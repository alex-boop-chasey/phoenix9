import { fireEvent, screen, within } from "@testing-library/react"
import { Route, Routes, useLocation } from "react-router"

import ProjectPage from "@/pages/ProjectPage"
import { projects } from "@/test/fixtures"
import { failure, mockApi } from "@/test/mockApi"
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

  it("header has Repo, VS Code and Start new build, and a Chat button", async () => {
    api()
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    const dock = within(screen.getByRole("group", { name: "Open project" }))
    expect(dock.getByRole("link", { name: "Repo" })).toHaveAttribute("href", "https://github.com/rebirth-wd/demo-site")
    expect(dock.getByRole("link", { name: "VS Code" })).toHaveAttribute("href", projects[0]!.vscode_url)
    expect(dock.getByRole("link", { name: "VS Code" })).toHaveAttribute("target", "_blank")
    expect(dock.queryByRole("button", { name: /chat/i })).toBeNull()
    expect(screen.getByRole("button", { name: /Chat/ })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Start new build" })).toHaveAttribute("href", "/p/demo-site/build?new=1")
    expect(screen.getByText("/srv/projects/demo-site")).toBeInTheDocument()
  })

  it("header Chat button shows the row's chat state", async () => {
    mockApi({
      "GET /api/projects/demo-site": { ...projects[0], chat: { state: "live", bridge_session_id: "s1", web_url: null, app_url: null, last_active: null } },
      "GET /api/gates": [],
      "GET /api/projects/demo-site/runs": [],
      "GET /api/projects/demo-site/changelog": [],
      "GET /api/events/recent": { events: [], next: 0 },
    })
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    expect(document.querySelector(".phead .chatdot")).toHaveClass("chatdot-live")
  })

  it("VS Code is greyed out with a tooltip when its address is not set", async () => {
    const reason = "Set the VS Code address in Global settings."
    mockApi({
      "GET /api/projects/demo-site": { ...projects[0], vscode_url: null, vscode: { url: null, reason } },
      "GET /api/gates": [],
      "GET /api/projects/demo-site/runs": [],
      "GET /api/projects/demo-site/changelog": [],
      "GET /api/events/recent": { events: [], next: 0 },
    })
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    const dock = within(screen.getByRole("group", { name: "Open project" }))
    expect(dock.queryByRole("link", { name: "VS Code" })).toBeNull()
    const button = dock.getByRole("button", { name: "VS Code" })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute("title", reason)
  })

  it("a missing repo is disabled", async () => {
    api("notes-only")
    renderAt("/p/notes-only/overview")
    await screen.findByRole("heading", { name: "notes-only" })
    const dock = within(screen.getByRole("group", { name: "Open project" }))
    expect(dock.getByRole("button", { name: "Repo" })).toBeDisabled()
  })
})

describe("ProjectPage for the agent folder", () => {
  it("shows a plain page with a way to the Agent panel", async () => {
    mockApi({ "GET /api/projects/home": failure(409, "This is the Phoenix agent's folder, not a project.") })
    renderAt("/p/home/overview")
    expect(await screen.findByText("This is the Phoenix agent's folder, not a project")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Open the Agent panel" })).toBeInTheDocument()
  })
})
