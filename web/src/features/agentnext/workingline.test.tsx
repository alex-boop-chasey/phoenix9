// The "Working…" line: one quiet line while the agent works, then a closed "N steps" list in plain words.
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import type { ToolCallItem } from "./components"
import { WorkingLine } from "./WorkingLine"

const c = (id: string, toolName: string, running: boolean): ToolCallItem => ({ toolCallId: id, toolName, running })

test("three running calls show ONE line with the newest call's words", () => {
  render(<WorkingLine running calls={[c("1", "library-profiles", true), c("2", "projects-list", true), c("3", "build-start", true)]} />)
  const line = screen.getByTestId("agent-working")
  expect(line).toHaveClass("ag-working")
  const live = within(line).getByText("Working… · Starting a build")
  expect(live).toHaveAttribute("aria-live", "polite")
  expect(screen.getAllByText(/^Working…/)).toHaveLength(1)
  expect(within(line).getByText("Show steps").closest("details")).not.toHaveAttribute("open")
  expect(screen.queryByText(/library-profiles|projects-list|build-start/)).toBeNull()
})

test("the line names the newest call still running", () => {
  render(<WorkingLine running calls={[c("1", "library-profiles", true), c("2", "projects-list", false)]} />)
  expect(screen.getByText("Working… · Checking project types")).toBeInTheDocument()
})

test("just Working… when no call runs, and no step list without calls", () => {
  render(<WorkingLine running calls={[]} />)
  expect(screen.getByText("Working…")).toBeInTheDocument()
  expect(screen.queryByText("Show steps")).toBeNull()
})

test("an unknown tool shows Working", () => {
  render(<WorkingLine running calls={[c("1", "mystery_tool", true)]} />)
  expect(screen.getByText("Working… · Working")).toBeInTheDocument()
  expect(screen.queryByText(/mystery_tool/)).toBeNull()
})

test("while working, the steps list shows this turn's calls newest last, a check on each done one", async () => {
  render(<WorkingLine running calls={[c("1", "library-profiles", false), c("2", "projects-list", true)]} />)
  await userEvent.click(screen.getByText("Show steps"))
  const items = screen.getAllByRole("listitem")
  expect(items.map((li) => li.textContent)).toEqual(["Checked project types", "Looking at your projects"])
  expect(within(items[0]!).getByRole("img", { name: "Done" })).toBeInTheDocument()
  expect(within(items[1]!).queryByRole("img", { name: "Done" })).toBeNull()
})

test("the finished summary says 3 steps and opens to the plain list", async () => {
  render(<WorkingLine running={false} calls={[c("1", "library-profiles", false), c("2", "projects-list", false), c("3", "mystery", false)]} />)
  const steps = screen.getByTestId("agent-steps")
  expect(steps.tagName).toBe("DETAILS")
  expect(steps).not.toHaveAttribute("open")
  await userEvent.click(screen.getByText("3 steps"))
  expect(steps).toHaveAttribute("open")
  expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Checked project types", "Looked at your projects", "Done a step"])
  expect(screen.queryByText(/Working/)).toBeNull()
})

test("one call says 1 step; no calls show nothing", () => {
  const { container, rerender } = render(<WorkingLine running={false} calls={[c("1", "search", false)]} />)
  expect(screen.getByText("1 step")).toBeInTheDocument()
  rerender(<WorkingLine running={false} calls={[]} />)
  expect(container).toBeEmptyDOMElement()
})
