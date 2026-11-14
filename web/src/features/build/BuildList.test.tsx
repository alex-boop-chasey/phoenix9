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



const show = (rows = BUILDS) =>
  renderWithProviders(<><BuildList name="demo-site" rows={rows} /><Where /></>, { route: "/p/demo-site/build" })

test("newest first with all columns", () => {
  show()
  const rows = screen.getAllByRole("row").slice(1)
  expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual(["Pricing page", "Blog section", "Contact form"])
  for (const h of ["Build", "Preset", "Tasks", "Result", "Duration", "Cost"]) {
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

test("a build that failed at a run step says where, with the reason on hover", () => {
  show([build({
    run_id: "s", title: "S", status: "failed", tasks_total: 3, tasks_passed: 3, tasks_failed: 0,
    failed_at: { step: "full-suite", title: "Full suite", reason: "2 tests failed", text: "Failed at: Full suite: 2 tests failed" },
  })])
  expect(screen.getByText("Failed at: Full suite").closest("[data-status]")).toHaveAttribute(
    "title", "Failed at: Full suite: 2 tests failed")
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

test("task bar: green passed, red failed, grey pending, blue running, orange only when the merge waits", () => {
  show([
    build({ run_id: "a", title: "A", status: "running", tasks_total: 4, tasks_passed: 1, tasks_failed: 1 }),
    build({ run_id: "b", title: "B", status: "waiting", tasks_total: 2, tasks_passed: 2, tasks_failed: 0 }),
  ])
  const bars = (id: string) =>
    [...document.querySelector(`[data-run=${id}] .tbar`)!.children].map((c) => c.className)
  expect(bars("a")).toEqual(["ok", "bad", "run", ""])
  expect(bars("b")).toEqual(["ok", "ok", "need"])
})

test("a skipped task has its own striped piece, and the hover counts passed, skipped and retried", () => {
  show([build({ run_id: "a", title: "A", status: "done", tasks_total: 6, tasks_passed: 5, tasks_failed: 0,
    tasks_skipped: 1, tasks_retried: 2 })])
  const bar = document.querySelector("[data-run=a] .tbar")!
  expect([...bar.children].map((c) => c.className)).toEqual(["ok", "ok", "ok", "ok", "ok", "skip"])
  expect(bar.getAttribute("title")).toBe("5 passed, 1 skipped · 2 tasks needed more than one try")
  expect(document.querySelector("[data-run=a] td.tcell")).toHaveAttribute("title", bar.getAttribute("title"))
})

test("no retry words when every task passed first try", () => {
  show([build({ run_id: "a", title: "A", status: "done", tasks_total: 3, tasks_passed: 3, tasks_failed: 0 })])
  expect(document.querySelector("[data-run=a] .tbar")).toHaveAttribute("title", "3 passed")
})

test("38 tasks fit: one thin bar split by colour in proportion", () => {
  show([build({ run_id: "a", title: "A", status: "running", tasks_total: 38, tasks_passed: 30, tasks_failed: 2,
    tasks_skipped: 1 })])
  const bar = document.querySelector("[data-run=a] .tbar") as HTMLElement
  expect(bar).toHaveClass("thin")
  const parts = [...bar.children] as HTMLElement[]
  expect(parts.map((c) => [c.className, c.dataset.count])).toEqual([
    ["ok", "30"], ["bad", "2"], ["skip", "1"], ["run", "1"], ["", "4"],
  ])
  expect(parts[0]!.style.flexGrow).toBe("30")
})

test("coloured left edge by result, and the selected row is marked", () => {
  show(BUILDS)
  const row = document.querySelector("[data-run=r-wait]") as HTMLElement
  expect(row.style.getPropertyValue("--spine")).toBe("var(--attn)")
  expect((document.querySelector("[data-run=r-fail]") as HTMLElement).style.getPropertyValue("--spine")).toBe("var(--bad)")
  expect((document.querySelector("[data-run=r-old]") as HTMLElement).style.getPropertyValue("--spine")).toBe("var(--ok)")
})

test("the selected build is highlighted", () => {
  renderWithProviders(<BuildList name="demo-site" rows={BUILDS} selected="r-fail" />, { route: "/p/demo-site/build" })
  expect(document.querySelector("tr.sel")).toHaveTextContent("Blog section")
})
