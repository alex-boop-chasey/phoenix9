import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { KeysForm } from "@/features/keys/KeysForm"
import type { KeyRow } from "@/lib/types"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const saved: KeyRow[] = [
  { name: "RESEND_API_KEY", secret: true, has_value: true, value_if_not_secret: null },
  { name: "PUBLIC_SITE_URL", secret: false, has_value: true, value_if_not_secret: "https://demo.test" },
]

const routes = (rows: KeyRow[] = saved, extra: Record<string, unknown> = {}) => ({
  "GET /api/projects/demo/keys": rows,
  "POST /api/projects/demo/keys/save": rows,
  ...extra,
})

async function renderSaved(rows: KeyRow[] = saved, extra: Record<string, unknown> = {}) {
  const api = mockApi(routes(rows, extra))
  renderWithProviders(<KeysForm mode="saved" project="demo" />)
  await screen.findByDisplayValue(rows[0]!.name)
  return api
}

const posts = (calls: MockRequest[]) => calls.filter((c) => c.method === "POST")

test("saved secret shows dots with reveal and remove", async () => {
  await renderSaved()
  expect(screen.getByDisplayValue("••••••")).toHaveAttribute("readonly")
  expect(screen.getByRole("button", { name: "Reveal" })).toBeInTheDocument()
  expect(screen.getAllByRole("button", { name: "Remove key" })).toHaveLength(2)
})

test("saved non-secret shows its value", async () => {
  await renderSaved()
  expect(screen.getByDisplayValue("https://demo.test")).not.toHaveAttribute("readonly")
})

test("reveal calls the endpoint and shows the value, hide hides it", async () => {
  const { calls } = await renderSaved(saved, {
    "POST /api/projects/demo/keys/reveal": { name: "RESEND_API_KEY", value: "re_123" },
  })
  await userEvent.click(screen.getByRole("button", { name: "Reveal" }))
  expect(await screen.findByDisplayValue("re_123")).toBeInTheDocument()
  expect(calls.find((c) => c.path.endsWith("/reveal"))!.body).toEqual({ name: "RESEND_API_KEY" })
  await userEvent.click(screen.getByRole("button", { name: "Hide" }))
  expect(screen.queryByDisplayValue("re_123")).toBeNull()
  expect(screen.getByDisplayValue("••••••")).toBeInTheDocument()
})

test("save saves without adding a row", async () => {
  const { calls } = await renderSaved()
  const before = screen.getAllByLabelText("Name").length
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({
    rows: [
      { name: "RESEND_API_KEY", secret: true },
      { name: "PUBLIC_SITE_URL", value: "https://demo.test", secret: false },
    ],
  })
  await waitFor(() => expect(screen.getAllByLabelText("Name").length).toBe(before))
})

test("add saves current rows then reveals an empty row", async () => {
  const { calls } = await renderSaved()
  const names = screen.getAllByLabelText("Name")
  await userEvent.type(names[names.length - 1]!, "NEW_KEY")
  const values = screen.getAllByLabelText("Value")
  await userEvent.type(values[values.length - 1]!, "abc")
  const before = screen.getAllByLabelText("Name").length
  await userEvent.click(screen.getByRole("button", { name: "Add" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toMatchObject({ rows: expect.arrayContaining([{ name: "NEW_KEY", value: "abc", secret: true }]) })
  await waitFor(() => expect(screen.getAllByLabelText("Name").length).toBe(before))
  const last = screen.getAllByLabelText("Name").at(-1) as HTMLInputElement
  expect(last.value).toBe("")
})

test("bad name refused inline and nothing sent", async () => {
  const { calls } = await renderSaved()
  const names = screen.getAllByLabelText("Name")
  const last = names[names.length - 1]!
  await userEvent.type(last, "1bad name")
  await userEvent.type(screen.getAllByLabelText("Value").at(-1)!, "x")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(last).toHaveAttribute("aria-invalid", "true")
  expect(screen.getByText(/letters, digits and underscores/)).toBeInTheDocument()
  expect(posts(calls)).toHaveLength(0)
})

test("duplicate name refused", async () => {
  const { calls } = await renderSaved()
  await userEvent.type(screen.getAllByLabelText("Name").at(-1)!, "RESEND_API_KEY")
  await userEvent.type(screen.getAllByLabelText("Value").at(-1)!, "x")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(screen.getByText(/two keys named RESEND_API_KEY/)).toBeInTheDocument()
  expect(posts(calls)).toHaveLength(0)
})

test("empty value refused", async () => {
  const { calls } = await renderSaved()
  await userEvent.type(screen.getAllByLabelText("Name").at(-1)!, "NO_VALUE")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(screen.getByText("Type a value for NO_VALUE.")).toBeInTheDocument()
  expect(posts(calls)).toHaveLength(0)
})

test("a saved row without a value says it needs one", async () => {
  await renderSaved([{ name: "SENTRY_DSN", secret: true, has_value: false, value_if_not_secret: null }])
  expect(screen.getByText("Needs a value")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(screen.getByText("Type a value for SENTRY_DSN.")).toBeInTheDocument()
})

test("remove asks for confirmation then calls remove", async () => {
  const { calls } = await renderSaved(saved, { "POST /api/projects/demo/keys/remove": [saved[1]] })
  await userEvent.click(screen.getAllByRole("button", { name: "Remove key" })[0]!)
  const dialog = await screen.findByRole("alertdialog")
  expect(within(dialog).getByText("Remove key RESEND_API_KEY?")).toBeInTheDocument()
  expect(posts(calls)).toHaveLength(0)
  await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({ name: "RESEND_API_KEY" })
  await waitFor(() => expect(screen.queryByDisplayValue("RESEND_API_KEY")).toBeNull())
})

test("local mode keeps rows in memory and never calls the api", async () => {
  const { calls } = mockApi({})
  const seen: unknown[] = []
  renderWithProviders(<KeysForm mode="local" onRowsChange={(rows) => seen.push(rows)} />)
  await userEvent.type(screen.getByLabelText("Name"), "TOKEN")
  await userEvent.type(screen.getByLabelText("Value"), "s3cret")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(screen.getByDisplayValue("••••••")).toBeInTheDocument()
  expect(screen.queryByDisplayValue("s3cret")).toBeNull()
  await userEvent.click(screen.getByRole("button", { name: "Reveal" }))
  expect(screen.getByDisplayValue("s3cret")).toBeInTheDocument()
  expect(seen.at(-1)).toEqual([{ name: "TOKEN", value: "s3cret", secret: true }])
  await userEvent.click(screen.getByRole("button", { name: "Remove key" }))
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Remove" }))
  await waitFor(() => expect(screen.queryByDisplayValue("TOKEN")).toBeNull())
  expect(calls).toHaveLength(0)
})

test("value never written to localStorage", async () => {
  const setItem = vi.spyOn(Storage.prototype, "setItem")
  mockApi({})
  renderWithProviders(<KeysForm mode="local" />)
  await userEvent.type(screen.getByLabelText("Name"), "TOKEN")
  await userEvent.type(screen.getByLabelText("Value"), "s3cret")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  fireEvent.click(screen.getByRole("button", { name: "Reveal" }))
  expect(setItem.mock.calls.flat().join(" ")).not.toContain("s3cret")
  setItem.mockRestore()
})

test("draft rows: no empty row, help and Optional tag show, a nameless row says what it needs", async () => {
  mockApi({})
  const wanted = [
    { service: "x", name: "X_SECRET", secret: true, required: true, help: "Find it in the X dashboard." },
    { service: "x", name: "X_OPTIONAL", secret: false, required: false, help: "Only if you use Y." },
  ]
  renderWithProviders(<KeysForm mode="local" draft wanted={wanted} />)
  await waitFor(() => expect(screen.getAllByLabelText("Name")).toHaveLength(2))
  expect(screen.getByText("Find it in the X dashboard.")).toBeInTheDocument()
  expect(screen.getByText("Only if you use Y.")).toBeInTheDocument()
  expect(screen.getAllByText("Optional")).toHaveLength(1)
  expect((screen.getAllByLabelText("Value")[1] as HTMLInputElement).type).toBe("text")
  await userEvent.click(screen.getByRole("button", { name: "Add" }))
  expect(screen.getAllByLabelText("Name")).toHaveLength(3)
  await userEvent.type(screen.getAllByLabelText("Value")[2]!, "abc")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(screen.getByText("Type a name for this key, or remove the row.")).toBeInTheDocument()
})
