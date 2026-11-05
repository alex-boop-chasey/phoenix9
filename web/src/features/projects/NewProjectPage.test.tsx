import { screen, waitFor, within } from "@testing-library/react"
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
    { name: "stripe", title: "Stripe", project_keys: [] },
    { name: "supabase", title: "Supabase", project_keys: [{ name: "SUPABASE_URL", secret: false, public: true, required: true, help: "The project address." }, { name: "SUPABASE_KEY", secret: true }] },
  ],
  problems: [],
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /api/info": info,
    "GET /api/github/repos": repos,
    "GET /api/library/templates": templates,
    "GET /api/library/services": services,
    "GET /api/library/profiles": { profiles: [
      { name: "web", title: "Web app", image: "" }, { name: "python-script", title: "Python script", image: "" },
    ], problems: [] },
    "GET /api/services": { supported: true, services: [
      { name: "supabase", title: "Supabase", connected: true },
      { name: "stripe", title: "Stripe", connected: false, account_keys: ["STRIPE_KEY"] },
    ] },
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
const createBtn = () => screen.getByRole("button", { name: "Create project" })

async function fillName(name = "my-site") {
  await userEvent.type(nameBox(), name)
  await screen.findByText(/name is free|already exists/i)
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
  expect(createBtn()).toBeDisabled()
})

test("existing name message", async () => {
  mockApi(routes())
  renderPage()
  await fillName("taken")
  expect(screen.getByText("A project called taken already exists.")).toBeInTheDocument()
  expect(createBtn()).toBeDisabled()
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

test("service tiles have no Connected dot; one that needs account keys says to set up first", async () => {
  mockApi(routes())
  renderPage()
  const supabase = await screen.findByRole("checkbox", { name: "Supabase" })
  expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeInTheDocument()
  expect(supabase.closest("label")).not.toHaveTextContent("Connected")
  const stripe = screen.getByRole("checkbox", { name: "Stripe" })
  const note = await within(stripe.closest("label")!).findByRole("link", { name: "Set up in Phoenix settings first" })
  expect(note).toHaveAttribute("href", "/settings")
  await userEvent.click(supabase)
  expect(screen.getByText("1 selected · adds 2 key rows below")).toBeInTheDocument()
})

const nameBoxes = () => screen.queryAllByLabelText("Name", { selector: "input[placeholder=NAME]" }) as HTMLInputElement[]
const valueBoxes = () => screen.getAllByLabelText("Value") as HTMLInputElement[]

test("ticking a service adds its key rows and unticking removes the empty ones", async () => {
  mockApi(routes())
  renderPage()
  const supabase = await screen.findByRole("checkbox", { name: "Supabase" })
  await userEvent.click(supabase)
  await waitFor(() => expect(nameBoxes().map((b) => b.value)).toEqual(["SUPABASE_URL", "SUPABASE_KEY"]))
  const [url, key] = valueBoxes()
  expect(url!.type).toBe("text")
  expect(key!.type).toBe("password")
  const receipt = screen.getByRole("complementary", { name: "What Phoenix will make" })
  expect(within(receipt).getByText("2 rows (2 need a value)")).toBeInTheDocument()
  await userEvent.click(supabase)
  await waitFor(() => expect(nameBoxes().map((b) => b.value)).toEqual([]))
  expect(within(receipt).queryByText(/key rows?|\d+ rows?/)).toBeNull()
  expect(within(receipt).getByText("Keys").nextElementSibling).toHaveTextContent("none")
})

test("unticking keeps a key row the user typed a value into and says so", async () => {
  mockApi(routes())
  renderPage()
  const supabase = await screen.findByRole("checkbox", { name: "Supabase" })
  await userEvent.click(supabase)
  await waitFor(() => expect(nameBoxes()).toHaveLength(2))
  await userEvent.type(valueBoxes()[0]!, "https://x.example")
  await userEvent.click(supabase)
  await waitFor(() => expect(nameBoxes().map((b) => b.value)).toEqual(["SUPABASE_URL"]))
  expect(screen.getByRole("status")).toHaveTextContent("Kept SUPABASE_URL because you typed a value")
})

test("repo search filters the dropdown", async () => {
  mockApi(routes())
  renderPage()
  await userEvent.click(screen.getByRole("radio", { name: "Existing GitHub repo" }))
  await userEvent.click(await screen.findByRole("combobox", { name: "GitHub repo" }))
  expect(await screen.findByText("rebirth-wd/demo-site")).toBeInTheDocument()
  await userEvent.type(screen.getByPlaceholderText("Search repos"), "tiny")
  await waitFor(() => expect(screen.queryByText("rebirth-wd/demo-site")).toBeNull())
  expect(screen.getByText("alex-boop-chasey/tiny-tool")).toBeInTheDocument()
})

test("template tiles prefill the kind and allow another GitHub template", async () => {
  mockApi(routes())
  renderPage()
  await userEvent.click(screen.getByRole("radio", { name: "Template" }))
  await userEvent.click(await screen.findByRole("radio", { name: "Python tool" }))
  expect(screen.getByRole("radio", { name: "Python script" })).toBeChecked()
  await userEvent.click(screen.getByRole("radio", { name: "Another GitHub template…" }))
  await userEvent.type(screen.getByLabelText("GitHub template"), "me/starter")
  expect(screen.getByText("me/starter template")).toBeInTheDocument()
})

test("the folder path box shows for code on this server", async () => {
  mockApi(routes())
  renderPage()
  await userEvent.click(screen.getByRole("radio", { name: "On this server" }))
  await userEvent.type(screen.getByLabelText("Folder on this server"), "/srv/old")
  expect(screen.getByText("Code in /srv/old")).toBeInTheDocument()
})

test("new repo on by default for empty and template, not for repo and folder", async () => {
  mockApi(routes())
  renderPage()
  const toggle = async () => screen.findByRole("switch", { name: "New GitHub repo" })
  expect(await toggle()).toBeChecked()
  await userEvent.click(screen.getByRole("radio", { name: "Existing GitHub repo" }))
  expect(screen.queryByRole("switch", { name: "New GitHub repo" })).toBeNull()
  await userEvent.click(screen.getByRole("radio", { name: "Template" }))
  expect(await toggle()).toBeChecked()
  await userEvent.click(screen.getByRole("radio", { name: "On this server" }))
  expect(screen.queryByRole("switch", { name: "New GitHub repo" })).toBeNull()
  await userEvent.click(screen.getByRole("radio", { name: "Empty" }))
  expect(await toggle()).toBeChecked()
})

test("owner tiles remember the choice", async () => {
  mockApi(routes())
  renderPage()
  const first = await screen.findByRole("radio", { name: "rebirth-wd" })
  await waitFor(() => expect(first).toBeChecked())
  await userEvent.click(screen.getByRole("radio", { name: "alex-boop-chasey" }))
  expect(localStorage.getItem("phoenix9.newRepoOwner")).toBe("alex-boop-chasey")
})

test("the receipt follows the choices and the missing item jumps to its step", async () => {
  mockApi(routes())
  renderPage()
  const receipt = screen.getByRole("complementary", { name: "What Phoenix will make" })
  expect(within(receipt).getByRole("link", { name: "Choose a name that is free." })).toBeInTheDocument()
  expect(createBtn()).toBeDisabled()
  await fillName("my-site")
  expect(within(receipt).getByText("/srv/projects/my-site")).toBeInTheDocument()
  expect(await within(receipt).findByText("rebirth-wd/my-site (new)")).toBeInTheDocument()
  expect(await within(receipt).findByText("Ready to create.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Add" }))
  await userEvent.type(screen.getByLabelText("Name", { selector: "input[placeholder=NAME]" }), "A_KEY")
  await userEvent.type(screen.getByLabelText("Value"), "v")
  const link = within(receipt).getByRole("link", { name: "Press Save under Project keys before creating." })
  expect(createBtn()).toBeDisabled()
  await userEvent.click(link)
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  expect(await within(receipt).findByText("1 row")).toBeInTheDocument()
  expect(createBtn()).toBeEnabled()
})

async function fillAndCreate(extra: Record<string, unknown>) {
  const api = mockApi(routes(extra))
  renderPage()
  await fillName("my-site")
  await userEvent.click(await screen.findByRole("checkbox", { name: "Supabase" }))
  await userEvent.click(screen.getByRole("button", { name: "Add" }))
  await userEvent.type(nameBoxes().at(-1)!, "API_TOKEN")
  await userEvent.type(valueBoxes().at(-1)!, "tok-1")
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  await waitFor(() => expect(createBtn()).toBeEnabled())
  await userEvent.click(createBtn())
  return api
}

const job = (over: object) => ({ id: "j1", kind: "create", project: "my-site", status: "running", steps: [], message: "", ...over })

test("create posts the documented body including keys", async () => {
  const { calls } = await fillAndCreate({
    "POST /api/projects": { job: "j1" },
    "GET /api/jobs/j1": job({}),
  })
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true))
  const post = calls.find((c) => c.method === "POST")!
  expect(post.body).toEqual({
    name: "my-site", description: "", source: { kind: "empty" }, profile: "web",
    new_repo: { on: true, owner: "rebirth-wd" }, services: ["supabase"],
    keys: [{ name: "API_TOKEN", value: "tok-1", secret: true }],
  })
})

test("the job id the server replies with (a plain string) is the one that gets polled", async () => {
  const { calls } = await fillAndCreate({
    "POST /api/projects": { job: "j1" },
    "GET /api/jobs/j1": job({ steps: [{ label: "Making the folder", status: "running" }] }),
  })
  await screen.findByText("Making the folder")
  expect(calls.some((c) => c.method === "GET" && c.path === "/api/jobs/j1")).toBe(true)
})

test("progress list updates from job polling", async () => {
  let n = 0
  mockApi(routes({
    "POST /api/projects": { job: "j1" },
    "GET /api/jobs/j1": () => {
      n += 1
      return n < 2
        ? job({ steps: [{ label: "Making the folder", status: "running" }] })
        : job({ steps: [{ label: "Making the folder", status: "done" }, { label: "Writing files", status: "running" }] })
    },
  }))
  renderPage()
  await fillName()
  await userEvent.click(createBtn())
  expect(await screen.findByRole("heading", { name: "Creating my-site…" })).toBeInTheDocument()
  expect(await screen.findByText("Making the folder")).toBeInTheDocument()
  expect(await screen.findByText("Writing files", {}, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByLabelText("Done")).toBeInTheDocument()
  expect(screen.getByTestId("spinner")).toBeInTheDocument()
})

test("done goes straight to the new project's Overview", async () => {
  mockApi(routes({
    "POST /api/projects": { job: "j1" },
    "GET /api/jobs/j1": job({ status: "done", steps: [{ label: "Switching the project chat on", status: "done" }] }),
  }))
  renderPage()
  await fillName()
  await userEvent.click(createBtn())
  expect(await screen.findByText("elsewhere")).toBeInTheDocument()
  expect(screen.getByTestId("where")).toHaveTextContent("/p/my-site/overview")
})

test("failure shows message and back keeps values", async () => {
  mockApi(routes({
    "POST /api/projects": { job: "j1" },
    "GET /api/jobs/j1": job({ status: "failed", message: "GitHub said no.", steps: [{ label: "Making the repo", status: "failed" }] }),
  }))
  renderPage()
  await fillName()
  await userEvent.click(createBtn())
  const alert = await screen.findByRole("alert")
  expect(within(alert).getByText("GitHub said no.")).toBeInTheDocument()
  expect(within(alert).getByText("Nothing was left half-made.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Back to the form" }))
  expect(nameBox()).toHaveValue("my-site")
  expect(screen.queryByLabelText("Description")).toBeNull()
})

test("no vscode or chat fields on the form", async () => {
  mockApi(routes())
  renderPage()
  await screen.findByRole("checkbox", { name: "Supabase" })
  expect(screen.queryByText(/vs ?code/i)).toBeNull()
  expect(screen.queryByLabelText(/chat/i)).toBeNull()
})
