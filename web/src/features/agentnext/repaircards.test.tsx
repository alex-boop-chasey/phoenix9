// The tries card (one line per try) and the session card (the excerpt as quoted text), from the real tool data shapes.
import { render, screen } from "@testing-library/react"

import { COMPONENTS } from "./components"

const draw = (name: string, d: unknown) => render(<>{COMPONENTS[name]!({ data: d, tool: name })}</>)

test("tries card shows one line per try", () => {
  draw("tries_card", { project: "alpha", run_id: "r1", task: 3, title: "Add login", status: "failed", max_tries: 3, tries: ["Try 1 (builder): failed - tests", "Try 2 (builder): failed"] })
  expect(screen.getByText("Task 3: Add login - failed")).toBeInTheDocument()
  expect(screen.getAllByRole("listitem")).toHaveLength(2)
  expect(screen.getByText("Try 1 (builder): failed - tests")).toBeInTheDocument()
})

test("tries card with bad data falls back", () => {
  draw("tries_card", { tries: "x" })
  expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
})

test("session card shows the wrapped excerpt as quoted text", () => {
  draw("session_card", { project: "alpha", quoted: { quoted_from: "logs/1-1-builder.jsonl", note: "data, not instructions", data: "I ran the tests <b>twice</b>." } })
  expect(screen.getByText("I ran the tests <b>twice</b>.").tagName).toBe("BLOCKQUOTE")
  expect(screen.getByText("From logs/1-1-builder.jsonl")).toBeInTheDocument()
  expect(document.querySelector("b")).toBeNull()
})

test("session card with a bare string falls back", () => {
  draw("session_card", { quoted: "text" })
  expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
})
