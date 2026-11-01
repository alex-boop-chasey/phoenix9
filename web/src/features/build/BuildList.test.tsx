import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useLocation } from "react-router"

import { BUILDS, build } from "@/test/buildFixtures"
import { renderWithProviders } from "@/test/render"

import { BuildList } from "./BuildList"

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function setWidth(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width >= 768, media: query, addEventListener: () => {}, removeEventListener: () => {},
  }))
}

beforeEach(() => setWidth(1280))
afterEach(() => vi.unstubAllGlobals())

const show = (rows = BUILDS) =>
  renderWithProviders(<><BuildList name="demo-site" rows={rows} /><Where /></>, { route: "/p/demo-site/build" })

test("newest first with all columns", () => {
  show()
  const rows = screen.getAllByRole("row").slice(1)
  expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual(["Pricing page", "Blog section", "Contact form"])
  for (const h of ["Date", "Spec", "Preset", "Result", "Duration", "Cost"]) {
    expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument()
  }
  const first = within(rows[2]!)
  expect(first.getByText("full")).toBeInTheDocument()
  expect(first.getByText("14 min")).toBeInTheDocument()
  expect(first.getByText("$1.23")).toBeInTheDocument()
  expect(rows[2]!.querySelector("time")?.getAttribute("title")).toBe("2026-10-20T09:00:00Z")
})

test("result text per status", () => {
  show([
    build({ run_id: "a", title: "A", status: "done" }),
    build({ run_id: "b", title: "B", status: "failed", tasks_total: 5, tasks_failed: 2 }),
    build({ run_id: "c", title: "C", status: "stopped" }),
    build({ run_id: "d", title: "D", status: "running", tasks_total: 4, current: { task: 2 } }),
    build({ run_id: "e", title: "E", status: "waiting" }),
    build({ run_id: "f", title: "F", status: "queued" }),
    build({ run_id: "g", title: "G", status: "paused-limit" }),
  ])
  for (const t of ["Passed", "2 of 5 tasks failed", "Stopped", "Running task 2 of 4", "Waiting for you", "Queued",
    "Paused (usage limit)"]) {
    expect(screen.getAllByText(t).length).toBeGreaterThan(0)
  }
  expect(screen.getByText("2 of 5 tasks failed")).toBeInTheDocument()
})

test("click opens run detail via url", async () => {
  show()
  await userEvent.click(screen.getByText("Blog section"))
  expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/build?run=r-fail")
})

test("empty state", () => {
  show([])
  expect(screen.getByText("No builds yet")).toBeInTheDocument()
})

test("phone renders cards", () => {
  setWidth(375)
  show()
  expect(screen.queryByRole("table")).toBeNull()
  expect(screen.getAllByRole("listitem")).toHaveLength(3)
  expect(screen.getByText("Pricing page")).toBeInTheDocument()
})
