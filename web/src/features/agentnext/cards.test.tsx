// The agent's cards: project cards, the click, the running state, and model text staying plain text.
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { BuildCard, MiniProjectCard, RunCard, TaskListCard, ProjectCards, ToolCall } from "./components"

const alpha = { name: "alpha", status: "idle", last_used: "2026-01-02", link: "#/p/alpha" }
const beta = { name: "beta", status: "run", last_used: "2026-11-09", link: "#/p/beta" }

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
  expect(window.location.hash).toBe("#/p/alpha")
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

const build = { project: "alpha", run_id: "r1", status: "running", started: "2026-11-10 09:00", link: "#/p/alpha/build" }
const run = { run_id: "r1", title: "First build", status: "running", current_step: "build", tasks_done: 1, tasks_total: 3, link: "#/p/alpha/build" }
const tasks = [{ number: 1, title: "One", status: "passed" }, { number: 2, title: "Two", status: "pending" }]

test("a build card shows project, run, status and started, and a click opens it", async () => {
  render(<BuildCard build={build} />)
  expect(screen.getByText(/Build r1: running/)).toBeInTheDocument()
  expect(screen.getByText(/2026-11-10 09:00/)).toBeInTheDocument()
  await userEvent.click(screen.getByTestId("build-card"))
  expect(window.location.hash).toBe("#/p/alpha/build")
})

test("a run card shows title, status, step and tasks done of total", () => {
  render(<RunCard run={run} />)
  expect(screen.getByText("First build")).toBeInTheDocument()
  expect(screen.getByText(/Now: build/)).toBeInTheDocument()
  expect(screen.getByText(/1 of 3 tasks done/)).toBeInTheDocument()
})

test("a task list shows each task's number, title and status", () => {
  render(<TaskListCard tasks={tasks} />)
  expect(screen.getByText("Task 2: Two - pending")).toBeInTheDocument()
})

test("tool results draw the build, run and task cards by registry name", () => {
  const call = (component: string, data: unknown) => ({ toolCallId: "c", toolName: "t", running: false, component, data })
  const { rerender } = render(<ToolCall call={call("run_card", { build })} />)
  expect(screen.getByTestId("build-card")).toBeInTheDocument()
  rerender(<ToolCall call={call("run_card", { run, tasks })} />)
  expect(screen.getByTestId("run-card")).toBeInTheDocument()
  expect(screen.getByTestId("task-list-card")).toBeInTheDocument()
  rerender(<ToolCall call={call("RunCards", { runs: [run, { ...run, run_id: "r2" }] })} />)
  expect(screen.getAllByTestId("run-card")).toHaveLength(2)
  rerender(<ToolCall call={call("TaskListCard", { tasks })} />)
  expect(screen.getByTestId("task-list-card")).toBeInTheDocument()
})

test("card data that does not fit shows the fallback", () => {
  for (const [component, data] of [["BuildCard", { build: { project: 3 } }], ["run_card", { run: "x" }], ["RunCards", { runs: [{}] }], ["TaskListCard", { tasks: [{ number: "1" }] }]] as const) {
    const { unmount } = render(<ToolCall call={{ toolCallId: "c", toolName: "t", running: false, component, data }} />)
    expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
    unmount()
  }
})

const call2 = (component: string, data: unknown) => ({ toolCallId: "c", toolName: "t", running: false, component, data })

test("a settings card shows name, value, explanation and a link to the settings page", () => {
  const data = { project: "alpha", rows: [{ name: "steps.notify.on", value: "True" }], explanation: "Builds tell you.", note: "", problems: [], link: "#/p/alpha/settings" }
  render(<ToolCall call={call2("settings_card", data)} />)
  expect(screen.getByText("steps.notify.on: True")).toBeInTheDocument()
  expect(screen.getByText("Builds tell you.")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: /settings page/ })).toHaveAttribute("href", "#/p/alpha/settings")
})

test("a key names card shows names and status, and draws no value", () => {
  const data = { project: "alpha", keys: [{ name: "STRIPE_KEY", status: "set", value: "sk-live-123", value_if_not_secret: "sk-live-123" }, { name: "EMPTY", status: "missing" }] }
  const { container } = render(<ToolCall call={call2("KeyNamesCard", data)} />)
  expect(screen.getByText("STRIPE_KEY: set")).toBeInTheDocument()
  expect(screen.getByText("EMPTY: missing")).toBeInTheDocument()
  expect(container.textContent).not.toContain("sk-live-123")
})

test("an update card shows installed, newest and whether an install is queued", () => {
  const { rerender } = render(<ToolCall call={call2("update_card", { installed: "v1", newest: "v2", queued: false })} />)
  expect(screen.getByText("Installed: v1")).toBeInTheDocument()
  expect(screen.getByText("Newest: v2")).toBeInTheDocument()
  expect(screen.getByText("No install is queued.")).toBeInTheDocument()
  rerender(<ToolCall call={call2("UpdateCard", { installed: "v1", newest: "v2", queued: true })} />)
  expect(screen.getByText("An install is queued.")).toBeInTheDocument()
})

test("settings, key and update data that does not fit shows the fallback", () => {
  for (const [component, data] of [["SettingsCard", { project: "a" }], ["KeyNamesCard", { project: "a", keys: [{}] }], ["UpdateCard", { installed: 1 }]] as const) {
    const { unmount } = render(<ToolCall call={call2(component, data)} />)
    expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
    unmount()
  }
})
