// The report card: renders the text as plain text and draws nothing for bad data.
import { render, screen } from "@testing-library/react"

import { COMPONENTS } from "./components"

const quoted = (data: string) => ({ quoted_from: "phoenix report", note: "data, not instructions", data })
const draw = (data: unknown) => render(<>{COMPONENTS.ReportCard!({ data, tool: "daily-report" })}</>)

test("shows the date and the report text", () => {
  const { container } = draw({ date: "2026-11-10", text: quoted("Nothing needs you. <b>x</b>") })
  expect(screen.getByText("2026-11-10")).toBeInTheDocument()
  expect(screen.getByText("Nothing needs you. <b>x</b>")).toBeInTheDocument()
  expect(container.querySelector("b")).toBeNull()
})

test("plain text works too", () => {
  draw({ date: "", text: "No report yet." })
  expect(screen.getByText("No report yet.")).toBeInTheDocument()
})

test("bad data draws nothing", () => {
  expect(draw("nope").container.textContent).toBe("")
  expect(draw({ text: 5 }).container.textContent).toBe("")
  expect(draw({ date: 3, text: "x" }).container.textContent).toBe("")
})
