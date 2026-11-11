// The "what happened" card: cause, tries, suggestion, one button per option, plain text, and nothing for bad data.
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { COMPONENTS, optionMessage } from "./components"

const data = {
  project: "alpha", run_id: "r1", cause: "Task 3 failed its checks.", tried: ["Try 1: tests failed", "Try 2: tests failed"],
  suggestion: "Retry task 3.",
  options: [{ label: "Retry task 3", tool: "repair_rerun_step", inputs: { project: "alpha", task: 3 } }, { label: "Skip task 3", tool: "repair_skip_task", inputs: { task: 3 } }],
}
const draw = (d: unknown, onSend?: (m: string) => void) => render(<>{COMPONENTS.WhatHappenedCard!({ data: d, tool: "what_happened", onSend })}</>)

test("shows the cause, what was tried and the suggestion", () => {
  draw(data)
  expect(screen.getByText("Task 3 failed its checks.")).toBeInTheDocument()
  expect(screen.getAllByRole("listitem")).toHaveLength(2)
  expect(screen.getByText(/Retry task 3\./)).toBeInTheDocument()
})

test("one button per option sends its fixed message", async () => {
  const sent: string[] = []
  draw(data, (m) => sent.push(m))
  expect(screen.getAllByRole("button")).toHaveLength(2)
  await userEvent.click(screen.getByRole("button", { name: "Skip task 3" }))
  expect(sent).toEqual([optionMessage(data.options[1]!)])
  expect(sent[0]).toContain("repair_skip_task")
})

test("HTML stays plain text", () => {
  draw({ ...data, cause: "<img src=x onerror=alert(1)>" })
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument()
  expect(document.querySelector("img")).toBeNull()
})

test("malformed data shows nothing", () => {
  const { container } = draw({ cause: 5, options: "x" })
  expect(container).toBeEmptyDOMElement()
  const bad = draw({ ...data, options: [{ label: "x" }] })
  expect(bad.container).toBeEmptyDOMElement()
})
