import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AgentMessage, Divider, MessageList, Notice, UserBubble, WorkingIndicator } from "@/features/agent/messages"
import type { AgentItem, UserItem } from "@/features/agent/useAgent"

const user = (o: Partial<UserItem> = {}): UserItem => ({ type: "user", line: 1, text: "hi", origin: "panel", at: "2026-11-07T14:00:00", ...o })

describe("messages", () => {
  it("UserBubble tags app and peer origins", () => {
    const { rerender } = render(<UserBubble item={user({ origin: "app" })} />)
    expect(screen.getByText("app")).toBeTruthy()
    rerender(<UserBubble item={user({ origin: "peer:scout" })} />)
    expect(screen.getByText("from scout")).toBeTruthy()
    rerender(<UserBubble item={user()} />)
    expect(screen.queryByText("app")).toBeNull()
    expect(screen.queryByText("waiting")).toBeNull()
  })
  it("AgentMessage shows markdown", () => {
    render(<AgentMessage markdown="**yes**" />)
    expect(screen.getByText("yes").tagName).toBe("STRONG")
  })
  it("Divider and Notice show their text", () => {
    render(<><Divider label="New conversation · 14:02" /><Notice item={{ type: "notice", line: 2, text: "Paused" }} /></>)
    expect(screen.getByText("New conversation · 14:02")).toBeTruthy()
    expect(screen.getByText("Paused")).toBeTruthy()
  })
  it("WorkingIndicator shows the action title", () => {
    render(<WorkingIndicator title="Reading files" />)
    expect(screen.getByText("Reading files")).toBeTruthy()
  })
  it("list shows empty state", () => {
    render(<MessageList items={[]} state="idle" />)
    expect(screen.getByText(/Ask about your projects/)).toBeTruthy()
  })
  it("list shows a queued pill until a matching user item arrives", () => {
    const queued: AgentItem = { type: "queued", line: 1, text: "later", pending: true, at: "2026-11-07T14:00:00" }
    const { rerender } = render(<MessageList items={[queued]} state="queued" />)
    expect(screen.getByText("waiting")).toBeTruthy()
    rerender(<MessageList items={[queued, user({ line: 2, text: "later" })]} state="working" />)
    expect(screen.queryByText("waiting")).toBeNull()
    expect(screen.getAllByText("later")).toHaveLength(1)
  })
  it("list shows session and date dividers, and the running action", () => {
    const items: AgentItem[] = [
      { type: "session", line: 0, session_id: "s" },
      user({ line: 1, at: "2026-11-06T14:02:00" }),
      { type: "thinking", line: 2, duration_s: 3, at: "2026-11-06T14:03:00" },
      { type: "agent", line: 3, markdown: "ok", at: "2026-11-07T09:00:00" },
      { type: "action", line: 4, id: "a", tool: "Bash", title: "Running tests", input_summary: "", status: "running" },
    ]
    render(<MessageList items={items} state="working" />)
    expect(screen.getByText("New conversation · 14:02")).toBeTruthy()
    expect(screen.getAllByRole("separator")).toHaveLength(2)
    expect(screen.getAllByText("Running tests").length).toBeGreaterThan(0)
  })
  it("thinking alone shows the indicator", () => {
    render(<MessageList items={[{ type: "thinking", line: 1, duration_s: 1, at: "2026-11-07T14:00:00" }]} state="working" />)
    expect(screen.getByTestId("agent-working")).toBeTruthy()
  })
  it("shows New messages when scrolled up and jumps down", () => {
    const a = user({ line: 1 })
    const { rerender } = render(<MessageList items={[a]} state="idle" />)
    const list = screen.getByTestId("agent-list")
    Object.defineProperty(list, "scrollHeight", { value: 1000, configurable: true })
    Object.defineProperty(list, "clientHeight", { value: 200, configurable: true })
    list.scrollTop = 0
    fireEvent.scroll(list)
    rerender(<MessageList items={[a, user({ line: 2, text: "more" })]} state="idle" />)
    fireEvent.click(screen.getByText("New messages"))
    expect(list.scrollTop).toBe(1000)
    expect(screen.queryByText("New messages")).toBeNull()
  })
})
