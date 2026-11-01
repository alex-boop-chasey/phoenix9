import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes, useLocation } from "react-router"

import NewProjectPage from "@/pages/NewProjectPage"
import { info } from "@/test/fixtures"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  localStorage.clear()
})

beforeEach(() => {
  Element.prototype.scrollIntoView = () => {}
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
})

const repos = {
  connected: true,
  repos: [
    { full_name: "rebirth-wd/demo-site", owner: "rebirth-wd", private: false },
    { full_name: "alex-boop-chasey/tiny-tool", owner: "alex-boop-chasey", private: true },
  ],
}
const templates = [
  { name: "next-site", title: "Next.js site", profile: "web", kind: "local", check: "" },
  { name: "py-cli", title: "Python tool", profile: "python-script", kind: "local", check: "" },
]
const services = {
  services: [
    { name: "github", title: "GitHub", project_keys: [] },
    { name: "supabase", title: "Supabase", project_keys: ["SUPABASE_URL"] },
  ],
  problems: [],
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /api/info": info,
    "GET /api/github/repos": repos,
    "GET /api/library/templates": templates,
    "GET /api/library/services": services,
    "GET /api/projects/check-name": (r: MockRequest) =>
      r.query.name === "taken" ? { ok: false, message: "A project called taken already exists." } : { ok: true, message: "Name is free." },
    ...extra,
  }
}

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderPage() {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/new" element={<NewProjectPage />} />
        <Route path="*" element={<div>elsewhere</div>} />
      </Routes>
      <Where />
    </>,
    { route: "/new" },
  )
}

const nameBox = () => screen.getByLabelText("Name", { selector: "#pf-name" })
const open = (el: HTMLElement) => fireEvent.pointerDown(el, { button: 0, ctrlKey: false, pointerType: "mouse" })

async function fillName(name = "my-site") {
  await userEvent.type(nameBox(), name)
  await screen.findByText(/Name is free|already exists/)
}

test("name checked live", async () => {
  const { calls } = mockApi(routes())
  renderPage()
  await fillName("my-site")
  const checks = calls.filter((c) => c.path === "/api/projects/check-name")
  expect(checks).toHaveLength(1) // debounced: one call, not one per letter
  expect(checks[0]!.query.name).toBe("my-site")
})

test("bad name message", async () => {
  const { calls } = mockApi(routes())
  renderPage()
  await userEvent.type(nameBox(), "Bad Name")
  expect(await screen.findByText(/lowercase letters, digits and dashes/)).toBeInTheDocument()
  expect(nameBox()).toHaveAttribute("aria-invalid", "true")
  expect(calls.some((c) => c.path === "/api/projects/check-name")).toBe(false)
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled()
})

test("existing name message", async () => {
  mockApi(routes())
  renderPage()
  await fillName("taken")
  expect(screen.getByText("A project called taken already exists.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled()
})

test("repo dropdown hidden when github not connected", async () => {
  mockApi(routes({ "GET /api/github/repos": { connected: false, repos: [] } }))
  renderPage()
  await screen.findByText(/to create a repo/)
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings")
  await userEvent.click(screen.getByLabelText("Existing GitHub repo"))
  expect(screen.queryByRole("combobox", { name: /repo/i })).toBeNull()
  expect(screen.queryByText("Choose a repo")).toBeNull()
})

test("services listed from the library", async () => {
  mockApi(routes())
  renderPage()
  expect(await screen.findByRole("checkbox", { name: "Supabase" })).toBeInTheDocument()
  expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeInTheDocument()
  expect(screen.getByText("Connecting service accounts comes in a later update.")).toBeInTheDocument()
})

test("repo search filters the dropdown", async () => {
  mockApi(routes())
  renderPage()
  await userEvent.click(screen.getByLabelText("Existing GitHub repo"))
  await userEvent.click(await screen.findByRole("combobox", { name: "GitHub repo" }))
  expect(await screen.findByText("rebirth-wd/demo-site")).toBeInTheDocument()
  await userEvent.type(screen.getByPlaceholderText("Search repos"), "tiny")
  await waitFor(() => expect(screen.queryByText("rebirth-wd/demo-site")).toBeNull())
  expect(screen.getByText("alex-boop-chasey/tiny-tool")).toBeInTheDocument()
})

test("template prefills profile", async () => {
  mockApi(routes())
  renderPage()
  await userEvent.click(screen.getByLabelText("Template"))
  open(await screen.findByRole("combobox", { name: "Template" }))
  fireEvent.click(await screen.findByRole("option", { name: "Python tool" }))
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Profile" })).toHaveTextContent("python-script"))
})

test("new repo on by default for empty and template, off for repo and code", async () => {
  mockApi(routes())
  renderPage()
  const toggle = async () => screen.findByRole("switch", { name: "New GitHub repo" })
  expect(await toggle()).toBeChecked()
  await userEvent.click(screen.getByLabelText("Existing GitHub repo"))
  expect(screen.queryByRole("switch", { name: "New GitHub repo" })).toBeNull()
  await userEvent.click(screen.getByLabelText("Template"))
  expect(await toggle()).toBeChecked()
  await userEvent.click(screen.getByLabelText("Code already on this server"))
  expect(screen.queryByRole("switch", { name: "New GitHub repo" })).toBeNull()
  await userEvent.click(screen.getByLabelText("Empty"))
  expect(await toggle()).toBeChecked()
})

test("owner choice remembered", async () => {
  mockApi(routes())
  renderPage()
  const owner = await screen.findByRole("combobox", { name: "Owner" })
  await waitFor(() => expect(owner).toHaveTextContent("rebirth-wd"))
  open(owner)
  fireEvent.click(await screen.findByRole("option", { name: "alex-boop-chasey" }))
  expect(localStorage.getItem("phoenix9.newRepoOwner")).toBe("alex-boop-chasey")
})

async function fillAndCreate(extra: Record<string, unknown>) {
  const api = mockApi(routes(extra))
  renderPage()
  await fillName("my-site")
  await userEvent.type(screen.getByLabelText("Description"), "A test site")
  await userEvent.click(await screen.findByRole("checkbox", { name: "Supabase" }))
  await userEvent.type(screen.getByLabelText("Name", { selector: "input[placeholder=NAME]" }), "API_TOKEN")
  await userEvent.type(screen.getByLabelText("Value"), "tok-1")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Create" })).toBeEnabled())
  await userEvent.click(screen.getByRole("button", { name: "Create" }))
  return api
}

const job = (over: object) => ({ id: "j1", kind: "create", project: "my-site", status: "running", steps: [], message: "", ...over })

test("create posts the documented body including keys", async () => {
  const { calls } = await fillAndCreate({
    "POST /api/projects": { job: job({}) },
    "GET /api/jobs/j1": job({}),
  })
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true))
  const post = calls.find((c) => c.method === "POST")!
  expect(post.body).toEqual({
    name: "my-site", description: "A test site", source: { kind: "empty" }, profile: "web",
    new_repo: { on: true, owner: "rebirth-wd" }, services: ["supabase"],
    keys: [{ name: "API_TOKEN", value: "tok-1", secret: true }],
  })
})

test("progress list updates from job polling", async () => {
  let n = 0
  mockApi(routes({
    "POST /api/projects": { job: job({}) },
    "GET /api/jobs/j1": () => {
      n += 1
      return n < 2
        ? job({ steps: [{ label: "Making the folder", status: "running" }] })
        : job({ steps: [{ label: "Making the folder", status: "done" }, { label: "Writing files", status: "running" }] })
    },
  }))
  renderPage()
  await fillName()
  await userEvent.click(screen.getByRole("button", { name: "Create" }))
  expect(await screen.findByText("Making the folder")).toBeInTheDocument()
  expect(await screen.findByText("Writing files", {}, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByLabelText("Done")).toBeInTheDocument()
  expect(screen.getByTestId("spinner")).toBeInTheDocument()
})

test("done navigates to the project page", async () => {
  mockApi(routes({
    "POST /api/projects": { job: job({}) },
    "GET /api/jobs/j1": job({ status: "done", steps: [{ label: "Done", status: "done" }] }),
  }))
  renderPage()
  await fillName()
  await userEvent.click(screen.getByRole("button", { name: "Create" }))
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/my-site/overview"))
})

test("failure shows message and back keeps values", async () => {
  mockApi(routes({
    "POST /api/projects": { job: job({}) },
    "GET /api/jobs/j1": job({ status: "failed", message: "GitHub said no.", steps: [{ label: "Making the repo", status: "failed" }] }),
  }))
  renderPage()
  await fillName()
  await userEvent.type(screen.getByLabelText("Description"), "keep me")
  await userEvent.click(screen.getByRole("button", { name: "Create" }))
  const alert = await screen.findByRole("alert")
  expect(within(alert).getByText("GitHub said no.")).toBeInTheDocument()
  expect(within(alert).getByText("Nothing was left half-made.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Back to the form" }))
  expect(nameBox()).toHaveValue("my-site")
  expect(screen.getByLabelText("Description")).toHaveValue("keep me")
})

test("no vscode or chat fields on the form", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByRole("checkbox", { name: "Supabase" })
  expect(screen.queryByText(/vs ?code/i)).toBeNull()
  expect(screen.queryByText(/chat/i)).toBeNull()
})
