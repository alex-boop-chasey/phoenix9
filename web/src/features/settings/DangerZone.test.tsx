import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { DangerZone } from "@/features/settings/DangerZone"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"
import type { DeletePlan, DeleteResult } from "@/lib/types"

afterEach(() => vi.unstubAllGlobals())

const plan: DeletePlan = {
  name: "demo", folder: "/srv/projects/demo", size: 2048, repo: "me/demo",
  open_prs: [{ number: 7, title: "Add login", url: "https://github.com/me/demo/pull/7" }],
  unpushed: 3, unsaved_edits: 2, runs: { count: 4 }, keys: ["API_KEY"], keep_days: 14,
  keys_note: "The saved keys are deleted and NOT kept in the safety copy.",
  chat: { unit: "claude-rc-chat@demo", state: "off" },
  deployments: [{ target: "vercel", note: "still live, take it down yourself", links: ["https://demo.example.com"] }],
  refusals: [], safety_copy: "/root/deleted-projects",
}
const done: DeleteResult = {
  name: "demo", backup: "/root/deleted-projects/demo-20261107-1530",
  steps: [{ step: "project folder", ok: true, words: "Removed." }, { step: "GitHub repo", ok: true, words: "Deleted me/demo." }],
  not_done: [], still_live: plan.deployments,
}
const scopeWords = "The GitHub repo me/demo was NOT deleted: Phoenix's GitHub login isn't allowed to delete repos."
const partial: DeleteResult = {
  ...done,
  steps: [done.steps[0]!, { step: "GitHub repo", ok: false, words: scopeWords }],
  not_done: [{ what: scopeWords, how: "Delete it on GitHub, or run `gh auth refresh -h github.com -s delete_repo` once in your own terminal and press Delete repo again." }],
}

async function open(routes: Record<string, unknown>, name = "demo") {
  const api = mockApi({ [`GET /api/projects/${name}/delete-plan`]: plan, ...routes })
  renderWithProviders(<DangerZone name={name} />)
  await userEvent.click(screen.getByRole("button", { name: /Delete project entirely/ }))
  return api
}
const deleteButton = () => screen.getByRole("button", { name: "Delete project entirely" })

test("hidden for phoenix9 and home", () => {
  for (const name of ["phoenix9", "home"]) {
    const { unmount } = renderWithProviders(<DangerZone name={name} />)
    expect(screen.queryByText("Danger zone")).toBeNull()
    unmount()
  }
})

test("shows both actions, the remove one explained", () => {
  renderWithProviders(<DangerZone name="demo" />)
  expect(screen.getByText("Danger zone")).toBeInTheDocument()
  expect(screen.getByText(/keeps every file; Import brings it back/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Remove from Phoenix" })).toBeInTheDocument()
})

test("shows the dry run in plain words", async () => {
  await open({})
  expect(await screen.findByText("/srv/projects/demo")).toBeInTheDocument()
  expect(screen.getByText("me/demo")).toBeInTheDocument()
  expect(screen.getByText(/#7 Add login/)).toBeInTheDocument()
  expect(screen.getByText(/3 commits never pushed/)).toBeInTheDocument()
  expect(screen.getByText(/2 unsaved edits \(never committed; kept in the safety copy\)/)).toBeInTheDocument()
  expect(screen.getByText(/4 Phoenix builds of history/)).toBeInTheDocument()
  expect(screen.getByText(/API_KEY/)).toBeInTheDocument()
  expect(screen.getByTestId("keys-note")).toHaveTextContent("NOT kept in the safety copy")
  expect(screen.getByText(/kept for 14 days/)).toBeInTheDocument()
  expect(screen.getByText(/claude-rc-chat@demo/)).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "https://demo.example.com" })).toBeInTheDocument()
})

test("refusals are shown and the button stays disabled", async () => {
  await open({ "GET /api/projects/demo/delete-plan": { ...plan, refusals: ["A build is running (r1). Stop it or let it finish first."] } })
  expect(await screen.findByText(/A build is running/)).toBeInTheDocument()
  expect(screen.queryByLabelText("Type demo to confirm")).toBeNull()
  expect(deleteButton()).toBeDisabled()
})

test("button is enabled only when the typed name matches exactly", async () => {
  await open({})
  const box = await screen.findByLabelText("Type demo to confirm")
  expect(deleteButton()).toBeDisabled()
  await userEvent.type(box, "dem")
  expect(deleteButton()).toBeDisabled()
  await userEvent.type(box, "o ")
  expect(deleteButton()).toBeDisabled()
  await userEvent.clear(box)
  await userEvent.type(box, "demo")
  expect(deleteButton()).toBeEnabled()
})

test("shows progress while deleting", async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  const { fetch: inner } = await open({ "POST /api/projects/demo/delete": done })
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") await gate
    return inner(input, init)
  })
  await userEvent.type(await screen.findByLabelText("Type demo to confirm"), "demo")
  await userEvent.click(deleteButton())
  expect(await screen.findByText(/Deleting… making the safety copy/)).toBeInTheDocument()
  expect(deleteButton()).toBeDisabled()
  release()
  expect(await screen.findByText(/Safety copy:/)).toBeInTheDocument()
})

test("success shows the safety copy path and the live deployments", async () => {
  const { calls } = await open({ "POST /api/projects/demo/delete": done })
  await userEvent.type(await screen.findByLabelText("Type demo to confirm"), "demo")
  await userEvent.click(deleteButton())
  expect(await screen.findByText("/root/deleted-projects/demo-20261107-1530")).toBeInTheDocument()
  expect(screen.getByText(/Still live, take it down yourself/)).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "https://demo.example.com" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Delete repo" })).toBeNull()
  expect(calls.find((c) => c.method === "POST")!.body).toEqual({ confirm: "demo" })
})

test("GitHub not deleted says what to do and Delete repo retries it", async () => {
  const { calls } = await open({
    "POST /api/projects/demo/delete": partial,
    "POST /api/projects/demo/delete-repo": { ...done, steps: [done.steps[1]], not_done: [] },
  })
  await userEvent.type(await screen.findByLabelText("Type demo to confirm"), "demo")
  await userEvent.click(deleteButton())
  expect(await screen.findByText(/gh auth refresh -h github.com -s delete_repo/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Delete repo" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/projects/demo/delete-repo")).toBe(true))
  await waitFor(() => expect(screen.queryByRole("button", { name: "Delete repo" })).toBeNull())
  expect(screen.queryByText(/gh auth refresh/)).toBeNull()
})

test("an error from the server is shown and nothing is claimed deleted", async () => {
  await open({ "POST /api/projects/demo/delete": failure(500, "The safety copy failed. Nothing was deleted.") })
  await userEvent.type(await screen.findByLabelText("Type demo to confirm"), "demo")
  await userEvent.click(deleteButton())
  expect(await screen.findByText("The safety copy failed. Nothing was deleted.")).toBeInTheDocument()
  expect(screen.queryByText(/Safety copy:/)).toBeNull()
})

test("a GitHub repo that is not the project's own is shown as kept", async () => {
  const why = "GitHub repo me/demo not deleted: it is not this project's own repo."
  const kept: DeleteResult = { ...done, steps: [done.steps[0]!, { step: "GitHub repo", ok: true, kept: true, words: why }] }
  await open({
    "GET /api/projects/demo/delete-plan": { ...plan, repo_delete: { repo: "me/demo", delete: false, why } },
    "POST /api/projects/demo/delete": kept,
  })
  expect(await screen.findByTestId("repo-verdict")).toHaveTextContent(why)
  await userEvent.type(await screen.findByLabelText("Type demo to confirm"), "demo")
  await userEvent.click(deleteButton())
  expect(await screen.findByText(/Kept: GitHub repo/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Delete repo" })).toBeNull()
})
