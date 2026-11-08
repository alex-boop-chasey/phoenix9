import { fireEvent, screen, waitFor } from "@testing-library/react"
import { vi } from "vitest"

import { ChatButton } from "@/components/ChatButton"
import type { ChatInfo, ChatState } from "@/lib/types"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

const info = (state: ChatState): ChatInfo => ({
  state, bridge_session_id: "sess1", web_url: "https://claude.ai/code/sess1", app_url: null, last_active: null,
})
const OPENED = {
  state: "live", web_url: "https://claude.ai/code/sess1", app_url: null, bridge_session_id: "sess1", message: "ok",
}
const PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"

afterEach(() => vi.restoreAllMocks())

test.each([
  ["sleeping", "chatdot-sleeping"], ["live", "chatdot-live"],
  ["working", "chatdot-working"], ["starting", "chatdot-starting"],
] as const)("%s shows the %s dot", (state, cls) => {
  renderWithProviders(<ChatButton project="demo" chat={info(state)} />)
  expect(document.querySelector(".chatdot")).toHaveClass(cls)
})

test("off and null show no dot, with the off tooltip", () => {
  renderWithProviders(<ChatButton project="demo" chat={info("off")} />)
  expect(document.querySelector(".chatdot")).toBeNull()
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveAttribute(
    "title", "off: pressing Chat starts a fresh conversation")
})

test("null chat is treated as off", () => {
  renderWithProviders(<ChatButton project="demo" chat={null} />)
  expect(document.querySelector(".chatdot")).toBeNull()
})

test("sleeping has its tooltip", () => {
  renderWithProviders(<ChatButton project="demo" chat={info("sleeping")} />)
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveAttribute("title", "asleep: it wakes when you write to it")
})

test("desktop opens the app link and shows the browser link", async () => {
  mockApi({ "POST /api/chat/demo/open": OPENED })
  const open = vi.spyOn(window, "open").mockImplementation(() => null)
  renderWithProviders(<ChatButton project="demo" chat={info("off")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(open).toHaveBeenCalledWith("claude://claude.ai/code/sess1"))
  expect(await screen.findByRole("link", { name: "Open in browser instead" }))
    .toHaveAttribute("href", "https://claude.ai/code/sess1")
})

test("a phone opens the https link", async () => {
  mockApi({ "POST /api/chat/demo/open": OPENED })
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(PHONE)
  const open = vi.spyOn(window, "open").mockImplementation(() => null)
  renderWithProviders(<ChatButton project="demo" chat={info("sleeping")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(open).toHaveBeenCalledWith("https://claude.ai/code/sess1"))
})

test("shows Starting chat… while the reply is pending", async () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})))
  renderWithProviders(<ChatButton project="demo" chat={info("off")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  expect(await screen.findByText("Starting chat…")).toBeInTheDocument()
})

test("an error shows the API's plain message", async () => {
  mockApi({ "POST /api/chat/demo/open": failure(409, "The chat could not start.") })
  renderWithProviders(<ChatButton project="demo" chat={info("off")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  expect(await screen.findByText("The chat could not start.")).toBeInTheDocument()
})

test("is an outlined button; compact is the small sidebar size", () => {
  const { unmount } = renderWithProviders(<ChatButton project="demo" chat={null} />)
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveClass("btn", "btn-secondary")
  expect(screen.getByRole("button", { name: /Chat/ })).not.toHaveClass("btn-sm")
  unmount()
  renderWithProviders(<ChatButton project="demo" chat={null} compact />)
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveClass("btn", "btn-secondary", "btn-sm")
})
