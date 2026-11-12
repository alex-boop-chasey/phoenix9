import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { failure, mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { ReferenceCard } from "./ReferenceCard"

afterEach(() => vi.unstubAllGlobals())

const P = "demo"
const URL_ = `GET /api/projects/${P}/reference`
const listed = {
  files: [{ name: "brand.css", size: 2048, modified: "2026-11-01T00:00:00Z", kind: "style" }],
  links: [{ url: "https://example.com/guide", note: "guide" }],
}

test("lists files and links and shows the summary", async () => {
  mockApi({ [URL_]: listed })
  renderWithProviders(<ReferenceCard project={P} />)
  expect(await screen.findByText("brand.css")).toBeInTheDocument()
  expect(screen.getByText("https://example.com/guide")).toBeInTheDocument()
  expect(screen.getByText("1 file and 1 link will be given to the build")).toBeInTheDocument()
})

test("says so when there is nothing yet", async () => {
  mockApi({ [URL_]: { files: [], links: [] } })
  renderWithProviders(<ReferenceCard project={P} />)
  expect(await screen.findByText("No reference material yet. Optional.")).toBeInTheDocument()
})

test("uploads a file as base64 and refreshes the list", async () => {
  let saved = false
  const { calls } = mockApi({
    [URL_]: () => (saved ? listed : { files: [], links: [] }),
    [`POST /api/projects/${P}/reference/files`]: () => { saved = true; return {} },
  })
  renderWithProviders(<ReferenceCard project={P} />)
  await screen.findByText("No reference material yet. Optional.")
  await userEvent.upload(screen.getByLabelText("Reference files"), new File(["body{}"], "brand.css", { type: "text/css" }))
  expect(await screen.findByText("brand.css")).toBeInTheDocument()
  const post = calls.find((c: MockRequest) => c.method === "POST")!
  expect(post.body).toEqual({ filename: "brand.css", data_base64: btoa("body{}") })
})

test("shows the server's refusal next to the file", async () => {
  mockApi({
    [URL_]: { files: [], links: [] },
    [`POST /api/projects/${P}/reference/files`]: failure(400, "That file looks like it holds a secret."),
  })
  renderWithProviders(<ReferenceCard project={P} />)
  await screen.findByText("No reference material yet. Optional.")
  await userEvent.upload(screen.getByLabelText("Reference files"), new File(["x"], "keys.txt"))
  expect(await screen.findByText(/That file looks like it holds a secret/)).toBeInTheDocument()
  expect(screen.getByText("keys.txt")).toBeInTheDocument()
})

test("removes a file", async () => {
  let gone = false
  const { calls } = mockApi({
    [URL_]: () => (gone ? { files: [], links: [] } : listed),
    [`POST /api/projects/${P}/reference/files/remove`]: () => { gone = true; return {} },
  })
  renderWithProviders(<ReferenceCard project={P} />)
  await userEvent.click(await screen.findByRole("button", { name: "Remove brand.css" }))
  await waitFor(() => expect(screen.queryByText("brand.css")).not.toBeInTheDocument())
  expect(calls.find((c) => c.path.endsWith("/files/remove"))!.body).toEqual({ filename: "brand.css" })
})

test("adds pasted links", async () => {
  const { calls } = mockApi({
    [URL_]: listed,
    [`POST /api/projects/${P}/reference/links`]: {},
  })
  renderWithProviders(<ReferenceCard project={P} />)
  await screen.findByText("brand.css")
  await userEvent.type(screen.getByLabelText(/Paste links/), "https://a.example.com | note")
  await userEvent.click(screen.getByRole("button", { name: "Add" }))
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true))
  expect(calls.find((c) => c.method === "POST")!.body).toEqual({ text: "https://a.example.com | note" })
})
