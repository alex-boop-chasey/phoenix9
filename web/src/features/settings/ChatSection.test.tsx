import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ChatSection } from "@/features/settings/ChatSection"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

const info = (state: string) => ({ state, bridge_session_id: null, web_url: null, app_url: null, last_active: null })

test("hidden when the chat is off", async () => {
  const { calls } = mockApi({ "GET /api/chat/demo": info("off") })
  renderWithProviders(<ChatSection name="demo" />)
  await waitFor(() => expect(calls.length).toBe(1))
  expect(screen.queryByText("Chat connection")).toBeNull()
})

test("running chat shows Sleep, which posts without asking", async () => {
  const { calls } = mockApi({ "GET /api/chat/demo": info("live"), "POST /api/chat/demo/sleep": info("sleeping") })
  renderWithProviders(<ChatSection name="demo" />)
  expect(await screen.findByText("Running")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Sleep" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/chat/demo/sleep")).toBe(true))
})

test("asleep chat has no Sleep button", async () => {
  mockApi({ "GET /api/chat/demo": info("sleeping") })
  renderWithProviders(<ChatSection name="demo" />)
  expect(await screen.findByText("Asleep")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Sleep" })).toBeNull()
})

test("Disconnect asks first, then posts off with confirm", async () => {
  const { calls } = mockApi({ "GET /api/chat/demo": info("sleeping"), "POST /api/chat/demo/off": info("off") })
  renderWithProviders(<ChatSection name="demo" />)
  await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }))
  expect(screen.getByText(/The chat's link stops working/)).toBeInTheDocument()
  expect(calls.some((c) => c.path.endsWith("/off"))).toBe(false)
  await userEvent.click(screen.getAllByRole("button", { name: "Disconnect" }).at(-1)!)
  await waitFor(() => expect(calls.find((c) => c.path === "/api/chat/demo/off")?.body).toEqual({ confirm: true }))
})

test("a server error is shown", async () => {
  mockApi({ "GET /api/chat/demo": info("live"), "POST /api/chat/demo/sleep": failure(409, "Could not sleep.") })
  renderWithProviders(<ChatSection name="demo" />)
  await userEvent.click(await screen.findByRole("button", { name: "Sleep" }))
  expect(await screen.findByText("Could not sleep.")).toBeInTheDocument()
})
