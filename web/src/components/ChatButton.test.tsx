/// <reference types="node" />
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { vi } from "vitest"

import { ChatButton, ChatSleepButton } from "@/components/ChatButton"
import type { ChatInfo, ChatState } from "@/lib/types"
import { failure, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

const info = (state: ChatState): ChatInfo => ({
  state, bridge_session_id: "sess1", web_url: "https://claude.ai/code/sess1", app_url: null, last_active: null,
})
const OPENED = {
  state: "awake", web_url: "https://claude.ai/code/sess1", app_url: null, bridge_session_id: "sess1", message: "ok",
  woke: true, fresh: false,
}
const PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

test.each(["asleep", "awake", "working"] as const)("%s shows its dot", (state) => {
  renderWithProviders(<ChatButton project="demo" chat={info(state)} />)
  expect(document.querySelector(".chatdot")).toHaveClass(`chatdot-${state}`)
})

test("waking shows the waking dot", () => {
  mockApi({ "GET /api/chat/demo": info("waking") })
  renderWithProviders(<ChatButton project="demo" chat={info("waking")} />)
  expect(document.querySelector(".chatdot")).toHaveClass("chatdot-waking")
})

test.each([
  ["none", "No chat yet: press to start one"], ["asleep", "Asleep: press to wake it"],
  ["awake", "Awake"], ["working", "Awake, working"],
] as const)("%s has its tooltip", (state, tip) => {
  renderWithProviders(<ChatButton project="demo" chat={info(state)} />)
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveAttribute("title", tip)
})

test("none and null keep the dot's space with an empty dot", () => {
  const { unmount } = renderWithProviders(<ChatButton project="demo" chat={info("none")} />)
  expect(document.querySelector(".chatdot")).toHaveClass("chatdot-none")
  unmount()
  renderWithProviders(<ChatButton project="demo" chat={null} />)
  expect(document.querySelector(".chatdot")).toHaveClass("chatdot-none")
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveAttribute("title", "No chat yet: press to start one")
})

test("a waking chat is fetched again until it is awake", async () => {
  let n = 0
  const { calls } = mockApi({ "GET /api/chat/demo": () => (++n > 1 ? info("awake") : info("waking")) })
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    renderWithProviders(<ChatButton project="demo" chat={info("waking")} />)
    await waitFor(() => expect(calls.length).toBe(1))
    await vi.advanceTimersByTimeAsync(3100)
    await waitFor(() => expect(document.querySelector(".chatdot")).toHaveClass("chatdot-awake"))
  } finally {
    vi.useRealTimers()
  }
})

test("desktop opens the app link and shows no extra links", async () => {
  mockApi({ "POST /api/chat/demo/open": OPENED })
  const open = vi.spyOn(window, "open").mockImplementation(() => null)
  renderWithProviders(<ChatButton project="demo" chat={info("none")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(open).toHaveBeenCalledWith("claude://claude.ai/code/sess1"))
  expect(screen.queryByRole("link")).toBeNull()
})

test("a phone opens the https link", async () => {
  mockApi({ "POST /api/chat/demo/open": OPENED })
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(PHONE)
  const open = vi.spyOn(window, "open").mockImplementation(() => null)
  renderWithProviders(<ChatButton project="demo" chat={info("asleep")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(open).toHaveBeenCalledWith("https://claude.ai/code/sess1"))
  expect(screen.queryByRole("link")).toBeNull()
})

test("pressing Chat again on an awake chat opens the same link straight away", async () => {
  const { calls } = mockApi({ "POST /api/chat/demo/open": OPENED })
  const open = vi.spyOn(window, "open").mockImplementation(() => null)
  renderWithProviders(<ChatButton project="demo" chat={info("awake")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  await waitFor(() => expect(open).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.getByRole("button", { name: /Chat/ })).not.toBeDisabled())
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  expect(open).toHaveBeenCalledTimes(2)
  expect(open).toHaveBeenLastCalledWith("claude://claude.ai/code/sess1")
  expect(calls.filter((c) => c.path === "/api/chat/demo/open")).toHaveLength(1)
})

test.each([["none", "Starting chat…"], ["asleep", "Waking chat…"]] as const)(
  "pending from %s reads %s, disabled, with a spinner", async (state, words) => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})))
    renderWithProviders(<ChatButton project="demo" chat={info(state)} />)
    fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
    const button = (await screen.findByText(words)).closest("button")!
    expect(button).toBeDisabled()
    expect(button.querySelector('[data-testid="spinner"]')).not.toBeNull()
  })

test("an error shows the API's plain message", async () => {
  mockApi({ "POST /api/chat/demo/open": failure(503, "The chat didn't wake in 60 seconds. Press Chat again.") })
  renderWithProviders(<ChatButton project="demo" chat={info("asleep")} />)
  fireEvent.click(screen.getByRole("button", { name: /Chat/ }))
  expect(await screen.findByRole("alert")).toHaveTextContent("The chat didn't wake in 60 seconds. Press Chat again.")
})

test("is an outlined button, the same size everywhere", () => {
  renderWithProviders(<ChatButton project="demo" chat={null} />)
  expect(screen.getByRole("button", { name: /Chat/ })).toHaveClass("btn", "btn-secondary")
  expect(screen.getByRole("button", { name: /Chat/ })).not.toHaveClass("btn-sm")
})

test.each(["none", "asleep", "waking"] as const)("Sleep is hidden when the chat is %s", (state) => {
  renderWithProviders(<ChatSleepButton project="demo" chat={info(state)} />)
  expect(screen.queryByRole("button", { name: "Sleep" })).toBeNull()
})

test.each(["awake", "working"] as const)("Sleep shows when %s and says so while pending", async (state) => {
  let answer: (r: Response) => void = () => {}
  const fetch = vi.fn((_url: RequestInfo | URL) => new Promise<Response>((r) => { answer = r }))
  vi.stubGlobal("fetch", fetch)
  renderWithProviders(<ChatSleepButton project="demo" chat={info(state)} />)
  fireEvent.click(screen.getByRole("button", { name: "Sleep" }))
  expect(await screen.findByText("Putting the chat to sleep…")).toBeInTheDocument()
  expect(String(fetch.mock.calls[0]?.[0])).toContain("/api/chat/demo/sleep")
  answer(new Response(JSON.stringify({ ok: true, data: { state: "asleep", changed: true, message: "ok" } })))
})

/** Every .ts/.tsx file under src. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    return statSync(p).isDirectory() ? sources(p) : /\.tsx?$/.test(f) ? [p] : []
  })
}

test("no old chat state words are left in the web code", () => {
  const old = /chatdot-(off|sleeping|starting|live)\b|state: "(sleeping|starting|live)"|offChat|\/off`/
  const hits = sources(join(process.cwd(), "src"))   // vitest runs in web/
    .filter((f) => !f.endsWith("ChatButton.test.tsx") && old.test(readFileSync(f, "utf8")))
  expect(hits).toEqual([])
})
