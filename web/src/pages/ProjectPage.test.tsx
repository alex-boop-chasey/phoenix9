import { fireEvent, screen } from "@testing-library/react"
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
  it("four tabs present", async () => {
    api()
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["overview", "build", "logs", "settings"])
  })

  it("tab change updates the url", async () => {
    api()
    renderAt("/p/demo-site/overview")
    const tab = await screen.findByRole("tab", { name: "logs" })
    fireEvent.mouseDown(tab)
    fireEvent.click(tab)
    expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/logs")
  })

  it("deep link opens the right tab", async () => {
    api()
    renderAt("/p/demo-site/settings")
    expect(await screen.findByRole("tab", { name: "settings" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
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

  it("vscode and chat links shown", async () => {
    api()
    renderAt("/p/demo-site/overview")
    await screen.findByRole("heading", { name: "demo-site" })
    const code = screen.getAllByRole("link", { name: "Open in VS Code" })
    expect(code[0]).toHaveAttribute("href", projects[0]!.vscode_url)
    expect(code[0]).toHaveAttribute("target", "_blank")
    expect(screen.getAllByRole("link", { name: "Chat" })[0]).toHaveAttribute("href", "https://claude.ai/code/session_demo_site")
  })
})
