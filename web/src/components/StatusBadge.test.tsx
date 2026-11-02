import { render, screen } from "@testing-library/react"

import { StatusBadge } from "@/components/StatusBadge"
import type { AnyStatus } from "@/lib/types"

const LABELS: [AnyStatus, string][] = [
  ["queued", "Queued"], ["pending", "Pending"], ["running", "Running"], ["waiting", "Waiting for you"],
  ["paused-limit", "Paused (usage limit)"], ["done", "Done"], ["passed", "Passed"], ["failed", "Failed"],
  ["stopped", "Stopped"], ["skipped", "Skipped"],
]

test.each(LABELS)("%s reads %s", (status, label) => {
  render(<StatusBadge status={status} />)
  expect(screen.getByText(label)).toBeInTheDocument()
})

test("running has spinner", () => {
  render(<StatusBadge status="running" />)
  expect(screen.getByTestId("spinner")).toBeInTheDocument()
})

test("done has no spinner", () => {
  render(<StatusBadge status="done" />)
  expect(screen.queryByTestId("spinner")).toBeNull()
})

const CLASSES: [AnyStatus, string][] = [
  ["done", "b-ok"], ["passed", "b-ok"], ["failed", "b-bad"], ["running", "b-run"],
  ["queued", "b-info"], ["pending", "b-info"], ["stopped", "b-info"], ["skipped", "b-info"],
  ["paused-limit", "b-info"], ["waiting", "b-need"],
]

test.each(CLASSES)("%s uses badge class %s", (status, cls) => {
  render(<StatusBadge status={status} />)
  const el = document.querySelector(`[data-status="${status}"]`)!
  expect(el).toHaveClass("badge", cls)
})
