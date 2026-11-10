// The agent's cards: project cards, the click, the running state, and model text staying plain text.
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { MiniProjectCard, ProjectCards, ToolCall } from "./components"

const alpha = { name: "alpha", status: "idle", last_used: "2026-01-02", link: "#/projects/alpha" }
const beta = { name: "beta", status: "run", last_used: "2026-11-09", link: "#/projects/beta" }

test("a project card shows name, status and last used", () => {
  render(<MiniProjectCard project={alpha} />)
  expect(screen.getByText("alpha")).toBeInTheDocument()
  expect(screen.getByText("idle")).toBeInTheDocument()
  expect(screen.getByText(/2026-01-02/)).toBeInTheDocument()
})

test("a list shows every project and a click opens that one", async () => {
  const opened: string[] = []
  render(<ProjectCards projects={[alpha, beta]} onOpen={(p) => opened.push(p.name)} />)
  expect(screen.getAllByTestId("mini-project-card")).toHaveLength(2)
  await userEvent.click(screen.getByText("beta"))
  expect(opened).toEqual(["beta"])
})

test("a click with no handler moves to the project's link", async () => {
  render(<MiniProjectCard project={alpha} />)
  await userEvent.click(screen.getByText("alpha"))
  expect(window.location.hash).toBe("#/projects/alpha")
})

test("a running tool shows a running state, a finished one its card", () => {
  const { rerender } = render(<ToolCall call={{ toolCallId: "c1", toolName: "list_projects", running: true }} />)
  expect(screen.getByTestId("tool-running")).toHaveTextContent("list_projects")
  rerender(<ToolCall call={{ toolCallId: "c1", toolName: "list_projects", running: false, component: "project_cards", data: { projects: [alpha] } }} />)
  expect(screen.queryByTestId("tool-running")).toBeNull()
  expect(screen.getByText("alpha")).toBeInTheDocument()
})

test("a tool with no component shows a plain Used line", () => {
  render(<ToolCall call={{ toolCallId: "c2", toolName: "suggest_next_actions", running: false }} />)
  expect(screen.getByText("Used suggest_next_actions")).toBeInTheDocument()
})

test("data that does not fit shows a plain fallback", () => {
  render(<ToolCall call={{ toolCallId: "c3", toolName: "list_projects", running: false, component: "project_cards", data: { projects: "nope" } }} />)
  expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
})

test("HTML in model text stays plain text", () => {
  const evil = { name: "<img src=x onerror=alert(1)>", status: "<b>bold</b>", last_used: "<script>x()</script>" }
  const { container } = render(<ProjectCards projects={[evil]} />)
  expect(container.querySelector("img, b, script")).toBeNull()
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument()
  expect(screen.getByText("<b>bold</b>")).toBeInTheDocument()
})
