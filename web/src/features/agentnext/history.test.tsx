// Unread conversations: the dot in the history list, cleared and told to the service once when opened; quiet note lines.
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { renderFullAgent } from "@/test/agentPanel"

/** Fake agent service: t1 is unread (a hand-off conversation with a note), t2 is read. Records every POST path. */
function mockService() {
  const posts: string[] = []
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost/").pathname.replace(/^.*agent-next\//, "")
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
    if (init?.method === "POST") {
      posts.push(path)
      return json(path === "threads" ? { id: "t9" } : {})
    }
    if (path === "threads") return json({ threads: [
      { id: "t1", title: "Fix demo task 3", created: 1, last_used: 1700000000, unread: true },
      { id: "t2", title: "Settings question", created: 1, last_used: 1600000000, unread: false },
    ] })
    if (path === "spend") return json({ month: "2026-11", used_share: 0.2, state: "plenty" })
    if (path === "threads/t1") return json({ thread: { id: "t1" }, running: false, events: [
      { number: 1, event: { type: "CUSTOM", name: "user_message", value: { id: "u1", text: "Please fix task 3." } } },
      { number: 2, event: { type: "CUSTOM", name: "note", value: { text: "Done on its own (Alex's hand-off rule): tried task 3 again." } } },
      { number: 3, event: { type: "CUSTOM", name: "note", value: { text: "Phoenix: the agent fixed demo task 3; the build goes on." } } },
    ] })
    return json({})
  }))
  return posts
}

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

test("an unread conversation has a dot before its title, which goes when it is opened; seen is posted once", async () => {
  const posts = mockService()
  renderFullAgent()
  const list = await screen.findByRole("navigation", { name: "Conversations" })
  const first = await within(list).findByRole("button", { name: /Fix demo task 3/ })
  expect(within(first).getByRole("img", { name: "Unread" })).toBeInTheDocument()
  expect(within(within(list).getByRole("button", { name: /Settings question/ })).queryByRole("img", { name: "Unread" })).toBeNull()

  await userEvent.click(first)
  await waitFor(() => expect(within(list).queryByRole("img", { name: "Unread" })).toBeNull())
  await waitFor(() => expect(posts.filter((p) => p === "threads/t1/seen")).toHaveLength(1))
  expect(posts.filter((p) => p.endsWith("/seen"))).toEqual(["threads/t1/seen"])
})

test("notes show as quiet plain lines in the conversation, not cards", async () => {
  mockService()
  localStorage.setItem("agent-next-thread", "t1")
  renderFullAgent()
  const line = await screen.findByText("Done on its own (Alex's hand-off rule): tried task 3 again.")
  expect(line).toHaveClass("ag-note")
  expect(line).toHaveAttribute("data-role", "note")
  expect(screen.getByText("Phoenix: the agent fixed demo task 3; the build goes on.")).toHaveClass("ag-note")
})
