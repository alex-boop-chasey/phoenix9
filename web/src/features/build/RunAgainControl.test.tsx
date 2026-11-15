import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useLocation } from "react-router"

import { runDetail } from "@/test/buildFixtures"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import type { RunDetail } from "@/lib/types"

import { RunAgainControl } from "./RunAgainControl"

afterEach(() => vi.unstubAllGlobals())

const AGAIN = "POST /api/runs/demo-site/r-wait/again"
const PRESETS = {
  presets: [
    { name: "full", title: "Full", has_file: true, description: "" },
    { name: "quick", title: "Quick", has_file: true, description: "" },
    { name: "custom", title: "Custom", has_file: false, description: "" },
  ],
}
const started = { run_id: "r-new", project: "demo-site", status: "queued", from_run: "r-wait", preset: null }
const routes = (over: Record<string, unknown> = {}) => ({
  "GET /api/library/presets": PRESETS,
  [AGAIN]: started,
  ...over,
})

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}
const show = (run: RunDetail) =>
  renderWithProviders(<><RunAgainControl name="demo-site" run={run} /><Where /></>, { route: "/p/demo-site/build?run=r-wait" })
const failed = (o: Partial<RunDetail> = {}) => runDetail({ status: "failed", gates: [], ...o })
const openDialog = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Run again" }))
  return screen.findByRole("alertdialog", { name: "Run this build again?" })
}
const posts = (calls: { method: string; path: string }[]) =>
  calls.filter((c) => c.method === "POST" && c.path.endsWith("/again"))

test.each(["failed", "stopped"] as const)("a %s build offers Run again", (status) => {
  mockApi(routes())
  show(runDetail({ status, gates: [] }))
  expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument()
})

test.each(["done", "running", "waiting", "queued"] as const)("a %s build has no Run again", (status) => {
  mockApi(routes())
  show(runDetail({ status, gates: [] }))
  expect(screen.queryByRole("button", { name: "Run again" })).toBeNull()
})

test("the dialog explains, defaults to the run's preset and hides custom when the run did not use it", async () => {
  mockApi(routes())
  show(failed())
  const dialog = await openDialog()
  expect(dialog).toHaveTextContent("Phoenix starts a new build from the same spec, reference documents and settings. This build stays as it is.")
  expect(dialog).toHaveTextContent("Change it only if you want this build to run differently.")
  const select = within(dialog).getByLabelText("Preset") as HTMLSelectElement
  await waitFor(() => expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Full", "Quick"]))
  expect(select.value).toBe("full")
  expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument()
})

test("a custom run's dialog lists Custom and starts on it", async () => {
  mockApi(routes())
  show(failed({ preset: "custom" }))
  const dialog = await openDialog()
  const select = within(dialog).getByLabelText("Preset") as HTMLSelectElement
  await waitFor(() => expect(within(select).getAllByRole("option").map((o) => o.textContent)).toContain("Custom"))
  expect(select.value).toBe("custom")
})

test("confirming unchanged posts only confirm and moves to the new run", async () => {
  const { calls } = mockApi(routes())
  show(failed())
  const dialog = await openDialog()
  await userEvent.click(within(dialog).getByRole("button", { name: "Run again" }))
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/demo-site/build?run=r-new"))
  expect(posts(calls)).toHaveLength(1)
  expect(posts(calls)[0]).toMatchObject({ body: { confirm: true } })
  expect(screen.queryByRole("alertdialog")).toBeNull()
})

test("a changed preset is sent along", async () => {
  const { calls } = mockApi(routes())
  show(failed({ status: "stopped" }))
  const dialog = await openDialog()
  const select = within(dialog).getByLabelText("Preset")
  await within(select).findByRole("option", { name: "Quick" })
  await userEvent.selectOptions(select, "quick")
  await userEvent.click(within(dialog).getByRole("button", { name: "Run again" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]).toMatchObject({ body: { confirm: true, preset: "quick" } })
})

test("a refusal shows the server's words and keeps the dialog open", async () => {
  mockApi(routes({ [AGAIN]: failure(409, "Another build is running in this project; wait for it to finish.") }))
  show(failed())
  const dialog = await openDialog()
  await userEvent.click(within(dialog).getByRole("button", { name: "Run again" }))
  expect(await within(dialog).findByText("Another build is running in this project; wait for it to finish.")).toBeInTheDocument()
  expect(screen.getByRole("alertdialog", { name: "Run this build again?" })).toBeInTheDocument()
  expect(screen.getByTestId("where")).toHaveTextContent("?run=r-wait")
})

test("a double click starts the build once, with a wheel while sending", async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  const { calls, fetch } = mockApi(routes())
  // hold the start answer back until the test lets it through
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/again")) await gate
    return fetch(input, init)
  })
  show(failed())
  const dialog = await openDialog()
  const confirm = within(dialog).getByRole("button", { name: "Run again" })
  await userEvent.dblClick(confirm)
  await waitFor(() => expect(confirm).toBeDisabled())
  expect(within(confirm).getByTestId("spinner")).toBeInTheDocument()
  await userEvent.click(confirm)
  release()
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("?run=r-new"))
  expect(posts(calls)).toHaveLength(1)
})
