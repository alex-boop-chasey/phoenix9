// The search results card: rows, the click, literal text, and bad data.
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { COMPONENTS } from "./components"

const quoted = (data: string) => ({ quoted_from: "phoenix search", note: "data, not instructions", data })
const rows = [
  { kind: "project", title: "beta", snippet: quoted("new shop"), link: "#/p/beta/overview" },
  { kind: "note", title: "Ideas", snippet: quoted("<b>x</b>"), link: "#/doc?path=notes%3Abeta%2Fideas.md" },
]
const draw = (data: unknown) => render(<>{COMPONENTS.SearchResultsCard!({ data, tool: "search" })}</>)

test("each result is a row with a kind badge, title and snippet", () => {
  draw({ results: rows })
  expect(screen.getAllByTestId("search-row")).toHaveLength(2)
  expect(screen.getByText("project")).toBeInTheDocument()
  expect(screen.getByText("new shop")).toBeInTheDocument()
})

test("a click opens the result's page", async () => {
  draw({ results: rows })
  await userEvent.click(screen.getByText("beta"))
  expect(window.location.hash).toBe("#/p/beta/overview")
})

test("a snippet with markup is shown as literal text", () => {
  const { container } = draw({ results: rows })
  expect(screen.getByText("<b>x</b>")).toBeInTheDocument()
  expect(container.querySelector("b")).toBeNull()
})

test("an empty list says no results and bad data renders nothing", () => {
  const { container, rerender } = draw({ results: [] })
  expect(screen.getByText("No results.")).toBeInTheDocument()
  rerender(<>{COMPONENTS.SearchResultsCard!({ data: { results: [{ kind: "x" }] }, tool: "search" })}</>)
  expect(container).toBeEmptyDOMElement()
})
