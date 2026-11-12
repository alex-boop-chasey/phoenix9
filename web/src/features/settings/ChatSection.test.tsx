import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ChatSection } from "@/features/settings/ChatSection"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const info = (state: string, last_active: number | null = null) =>
  ({ state, bridge_session_id: null, web_url: null, app_url: null, last_active })
const changed = (state: string) => ({ state, changed: true, message: "Done." })

test("no chat yet still shows the section, with no buttons", async () => {
  mockApi({ "GET /api/chat/demo": info("none") })
  renderWithProviders(<ChatSection name="demo" />)
  expect(await screen.findByText("No chat yet")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Sleep" })).toBeNull()
  expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull()
})

test("awake chat shows Sleep, which posts without asking", async () => {
  const { calls } = mockApi({ "GET /api/chat/demo": info("awake"), "POST /api/chat/demo/sleep": changed("asleep") })
  renderWithProviders(<ChatSection name="demo" />)
  expect(await screen.findByText("Awake")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Sleep" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/chat/demo/sleep")).toBe(true))
})

test("asleep chat says when it was last used and has no Sleep button", async () => {
  mockApi({ "GET /api/chat/demo": info("asleep", Date.now() / 1000 - 3 * 3600) })
  renderWithProviders(<ChatSection name="demo" />)
  expect(await screen.findByText("Asleep, last used 3 hours ago")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Sleep" })).toBeNull()
})

test("Start a fresh chat asks first, then posts forget with confirm", async () => {
  const { calls } = mockApi({ "GET /api/chat/demo": info("asleep"), "POST /api/chat/demo/forget": changed("none") })
  renderWithProviders(<ChatSection name="demo" />)
  await userEvent.click(await screen.findByRole("button", { name: "Start a fresh chat" }))
  expect(screen.getByText(/The old conversation stays in your Claude app/)).toBeInTheDocument()
  expect(calls.some((c) => c.path.endsWith("/forget"))).toBe(false)
  await userEvent.click(screen.getByRole("button", { name: "Forget saved chat" }))
  await waitFor(() => expect(calls.find((c) => c.path === "/api/chat/demo/forget")?.body).toEqual({ confirm: true }))
})

test("a server error is shown", async () => {
  mockApi({ "GET /api/chat/demo": info("awake"), "POST /api/chat/demo/sleep": failure(409, "Could not sleep.") })
  renderWithProviders(<ChatSection name="demo" />)
  await userEvent.click(await screen.findByRole("button", { name: "Sleep" }))
  expect(await screen.findByText("Could not sleep.")).toBeInTheDocument()
})
