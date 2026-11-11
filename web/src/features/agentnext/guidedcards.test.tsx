// The approval summaries and the plan check, specs and job cards.
import { render, screen } from "@testing-library/react"

import { ApprovalCard } from "./approval"
import { ToolCall } from "./components"

const create = { approvalId: "a", toolName: "project-create", decision: "pending" as const,
  input: { name: "shop", profile: "web", source: { kind: "template", template: "react-vite" }, new_repo: { on: true, owner: "alex" }, services: ["stripe", "db"] } }

test("project-create shows plain lines", () => {
  render(<ApprovalCard item={create} onDecide={() => {}} />)
  const t = screen.getByTestId("approval-summary").textContent
  expect(t).toContain("Name: shop")
  expect(t).toContain("Framework: react-vite")
  expect(t).toContain("Services: stripe, db")
  expect(t).toContain("New GitHub repo under alex")
})

test("project-create without a repo says no new repo", () => {
  render(<ApprovalCard item={{ ...create, input: { name: "x" } }} onDecide={() => {}} />)
  expect(screen.getByTestId("approval-summary").textContent).toContain("No new repo")
})

test("hotfix-start shows the whole brief inside a scrollable block", () => {
  const brief = "Line one\n  indented\n" + "long ".repeat(2000)
  render(<ApprovalCard item={{ approvalId: "b", toolName: "hotfix-start", decision: "pending", input: { name: "shop", brief } }} onDecide={() => {}} />)
  const block = screen.getByTestId("approval-brief")
  expect(block.textContent).toBe(brief)
  expect(block.className).toContain("overflow-y-auto")
  expect(block.className).toContain("max-h-60")
  expect(screen.getByText("Starts a short build on its own branch")).toBeInTheDocument()
})

test("malformed approval input shows no summary", () => {
  render(<ApprovalCard item={{ ...create, input: "oops" }} onDecide={() => {}} />)
  expect(screen.queryByTestId("approval-summary")).toBeNull()
})

const call = (component: string, data: unknown) => ({ toolCallId: "c", toolName: "t", running: false, component, data })

test("plan check card shows steps and errors", () => {
  render(<ToolCall call={call("PlanCheckCard", { project: "p", groups: { build: ["a", "b"] }, errors: ["bad step"] })} />)
  const t = screen.getByTestId("plan-check-card").textContent
  expect(t).toContain("build: 2 steps")
  expect(t).toContain("Problem: bad step")
  expect(t).toContain("The plan has problems.")
})

test("specs card says which can be built directly", () => {
  render(<ToolCall call={call("SpecsCard", { project: "p", specs: [{ name: "a.md", title: "A", task_format: true }, { name: "b.md", title: "B", task_format: false }] })} />)
  const t = screen.getByTestId("specs-card").textContent
  expect(t).toContain("a.md: A - can be built directly")
  expect(t).toContain("b.md: B - needs a plan first")
})

test("job card shows steps, then Done or the failure", () => {
  const steps = [{ label: "Make folder", status: "done" }]
  const { unmount } = render(<ToolCall call={call("JobCard", { kind: "create", project: "p", status: "done", steps, message: "" })} />)
  expect(screen.getByTestId("job-card").textContent).toContain("Make folder: done")
  expect(screen.getByTestId("job-result").textContent).toBe("Done")
  unmount()
  render(<ToolCall call={call("JobCard", { status: "failed", steps, message: "no disk" })} />)
  expect(screen.getByTestId("job-result").textContent).toBe("Failed: no disk")
})

test("malformed data shows the fallback line", () => {
  for (const c of ["PlanCheckCard", "SpecsCard", "JobCard"]) {
    const { unmount } = render(<ToolCall call={call(c, { groups: 5, specs: "x", steps: 3 })} />)
    expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
    unmount()
  }
})
