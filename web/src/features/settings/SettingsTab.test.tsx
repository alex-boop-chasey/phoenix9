import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { SettingsTab } from "@/features/settings/SettingsTab"
import { mockApi, type MockRequest } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import { baseRoutes, settingsView } from "@/test/settingsFixtures"

afterEach(() => vi.unstubAllGlobals())

const posts = (calls: MockRequest[]) => calls.filter((c) => c.method === "POST" && !c.path.endsWith("/plan"))

async function setup(name = "demo-site", extra: Record<string, unknown> = {}) {
  const api = mockApi({ ...baseRoutes(name), ...extra })
  renderWithProviders(<SettingsTab name={name} />)
  await screen.findByRole("button", { name: "Save build settings" })
  await screen.findByRole("button", { name: "Save project" })
  await screen.findByText("Writes the code for the task.")
  return api
}

const saved = (name = "demo-site") => ({ [`POST /api/projects/${name}/settings`]: settingsView })

test("project save sends changed fields", async () => {
  const { calls } = await setup("demo-site", { "POST /api/projects/demo-site/edit": { ...baseRoutes()["GET /api/projects/demo-site"], description: "New text" } })
  expect(screen.getByRole("button", { name: "Save project" })).toBeDisabled()
  const desc = screen.getByLabelText("Description")
  await userEvent.clear(desc)
  await userEvent.type(desc, "New text")
  expect(screen.getByText("Unsaved changes")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Save project" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({ description: "New text" })
})

test("repo change asks for confirmation and sends confirm", async () => {
  const { calls } = await setup("demo-site", { "POST /api/projects/demo-site/edit": baseRoutes()["GET /api/projects/demo-site"] })
  const repo = screen.getByLabelText("GitHub repo")
  await userEvent.clear(repo)
  await userEvent.type(repo, "rebirth-wd/other")
  await userEvent.click(screen.getByRole("button", { name: "Save project" }))
  expect(await screen.findByText("Change the repo/profile?", { selector: "h2" })).toBeInTheDocument()
  expect(posts(calls)).toHaveLength(0)
  await userEvent.click(screen.getByRole("button", { name: "Change it" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({ repo: "rebirth-wd/other", confirm: true })
})

test("keys form present in saved mode", async () => {
  await setup()
  expect(screen.getByText("Project keys")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument()
  expect(screen.getByText("Changes are picked up by the next build and the next chat restart.")).toBeInTheDocument()
})

test("build save sends only changed dotted keys", async () => {
  const { calls } = await setup("demo-site", saved())
  expect(screen.getByRole("button", { name: "Save build settings" })).toBeDisabled()
  await userEvent.click(screen.getByRole("radio", { name: /Ask me first/ }))
  await userEvent.click(screen.getByRole("switch", { name: "Reviewer" }))
  await userEvent.click(screen.getByRole("button", { name: "Reviewer settings" }))
  await userEvent.type(screen.getByLabelText("Model"), "claude-x")
  await userEvent.click(screen.getByRole("button", { name: "Save build settings" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({
    set: { merge: "ask", "steps.reviewer.on": false, "steps.reviewer.model": "claude-x" },
  })
  expect(await screen.findByRole("button", { name: "Save build settings" })).toBeDisabled()
})

test("build save sends typed values (numbers, booleans, lists)", async () => {
  const { calls } = await setup("demo-site", saved())
  await userEvent.clear(screen.getByLabelText("Tries per task"))
  await userEvent.type(screen.getByLabelText("Tries per task"), "5")
  await userEvent.click(screen.getByRole("button", { name: "Builder settings" }))
  await userEvent.type(screen.getByLabelText("Tools denied"), "Bash, Write")
  await userEvent.click(screen.getByRole("switch", { name: "Advisor on" }))
  await userEvent.click(screen.getByRole("button", { name: "Save build settings" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({
    set: { max_tries: 5, "steps.builder.tools_denied": ["Bash", "Write"], "steps.builder.advisor.on": true },
  })
})

test("server validation errors listed and nothing marked saved", async () => {
  mockApi(baseRoutes())
  const base = (globalThis.fetch as unknown as (...a: unknown[]) => Promise<Response>)
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "POST" && String(input).endsWith("/settings")) {
      return new Response(JSON.stringify({ ok: false, message: "unknown key 'x'; max_tries must be 1-10" }), { status: 400 })
    }
    return base(input, init)
  }))
  renderWithProviders(<SettingsTab name="demo-site" />)
  await screen.findByRole("button", { name: "Save build settings" })
  await userEvent.click(await screen.findByRole("radio", { name: /Ask me first/ }))
  await userEvent.click(screen.getByRole("button", { name: "Save build settings" }))
  const alert = await screen.findByRole("alert")
  expect(within(alert).getByText("unknown key 'x'")).toBeInTheDocument()
  expect(within(alert).getByText("max_tries must be 1-10")).toBeInTheDocument()
  expect(screen.getByText("Unsaved changes")).toBeInTheDocument()
})

test("reset to preset confirms then posts", async () => {
  const { calls } = await setup("demo-site", { "POST /api/projects/demo-site/settings/preset": settingsView })
  expect(screen.queryByText("Use Reset to preset to apply a preset's values.")).toBeNull()
  await userEvent.click(screen.getByRole("radio", { name: /Quick/ }))
  expect(screen.getByText("Use Reset to preset to apply a preset's values.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Reset to preset" }))
  expect(posts(calls)).toHaveLength(0)
  const dialog = await screen.findByRole("alertdialog")
  await userEvent.click(within(dialog).getByRole("button", { name: "Reset to preset" }))
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0]!.body).toEqual({ preset: "quick" })
})

test("explain dialog shows the step list", async () => {
  await setup()
  await userEvent.click(screen.getByRole("button", { name: "Show the effective step list" }))
  const dialog = await screen.findByRole("dialog")
  expect(await within(dialog).findByText("Plan check")).toBeInTheDocument()
  expect(within(dialog).getAllByRole("listitem")).toHaveLength(7)
  expect(within(dialog).getByText(/max_tries = 3/)).toBeInTheDocument()
})

test("on failure options explained", async () => {
  await setup()
  expect(screen.getByText("Continue")).toBeInTheDocument()
  expect(screen.getByText("Move on to tasks that don't depend on the failed one, and flag it.")).toBeInTheDocument()
  expect(screen.getByText("Pause for me")).toBeInTheDocument()
  expect(screen.getByText("Pause and show an escalation; press Acknowledged when fixed.")).toBeInTheDocument()
  expect(screen.getByText("Delegate to the project chat")).toBeInTheDocument()
  expect(screen.getByText("The project's chat tries to fix it and only alerts you if it can't.")).toBeInTheDocument()
  expect(screen.getByRole("radio", { name: /Pause for me/ })).toBeChecked()
})

test("phoenix9 merge locked to ask", async () => {
  await setup("phoenix9")
  expect(screen.getByRole("radio", { name: /Ask me first/ })).toBeChecked()
  expect(screen.getByRole("radio", { name: /Merge automatically/ })).toBeDisabled()
  expect(screen.getByText("Phoenix's own project always asks before merging.")).toBeInTheDocument()
})
