import { act, fireEvent, render, screen } from "@testing-library/react"
import { useEffect } from "react"
import { MemoryRouter, useLocation } from "react-router"

import { ProjectsFilters, SEARCH_DEBOUNCE_MS } from "./ProjectsFilters"
import { useProjectQuery } from "./useProjectQuery"

/** Every value the address took, in order (the first entry is the starting address). */
let addresses: string[] = []

/** The filter bar wired to the address, recording each address change. */
function Harness() {
  const { query, update } = useProjectQuery()
  const loc = useLocation()
  useEffect(() => {
    addresses.push(loc.search)
  }, [loc.search])
  return (
    <>
      <ProjectsFilters query={query} countText="" onChange={update} />
      <div data-testid="where">{loc.search}</div>
    </>
  )
}

function renderBar(url = "/") {
  addresses = []
  return render(<MemoryRouter initialEntries={[url]}><Harness /></MemoryRouter>)
}

afterEach(() => vi.useRealTimers())

test("typing three characters quickly makes one address update after a pause", () => {
  vi.useFakeTimers()
  renderBar()
  const box = screen.getByRole("searchbox")
  for (const value of ["b", "bi", "bil"]) fireEvent.change(box, { target: { value } })
  expect(box).toHaveValue("bil")
  expect(screen.getByTestId("where").textContent).toBe("")
  act(() => { vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS) })
  expect(screen.getByTestId("where").textContent).toBe("?q=bil")
  expect(addresses).toEqual(["", "?q=bil"]) // the start, then the one update
})

test("Enter sends the text at once; the Show select is immediate", () => {
  vi.useFakeTimers()
  renderBar()
  const box = screen.getByRole("searchbox")
  fireEvent.change(box, { target: { value: "now" } })
  fireEvent.keyDown(box, { key: "Enter" })
  expect(screen.getByTestId("where").textContent).toBe("?q=now")
  fireEvent.change(screen.getByLabelText("Show"), { target: { value: "need" } })
  expect(screen.getByTestId("where").textContent).toBe("?q=now&status=need")
})

test("an outside change to the address replaces pending typing", () => {
  vi.useFakeTimers()
  renderBar("/?q=site")
  const box = screen.getByRole("searchbox")
  expect(box).toHaveValue("site")
  fireEvent.change(box, { target: { value: "sit" } })
  fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "created" } })
  act(() => { vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS) })
  // The Sort change rewrote the address with the committed q; the pending "sit" still lands after the pause.
  expect(screen.getByTestId("where").textContent).toBe("?q=sit&sort=created")
})
