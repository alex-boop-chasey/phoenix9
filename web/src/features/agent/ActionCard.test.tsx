import { fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ActionCard, ActionGroup, toolIcon } from "@/features/agent/ActionCard"
import { MessageList } from "@/features/agent/messages"
import type { ActionItem } from "@/features/agent/useAgent"

const act = (o: Partial<ActionItem> = {}): ActionItem => ({
  type: "action", line: 1, id: "t1", tool: "Bash", title: "Run the tests", input_summary: "pytest -q", status: "ok", ...o,
})

describe("ActionCard", () => {
  it("picks an icon per tool", () => {
    const names: Record<string, string> = {
      Bash: "terminal", Edit: "pencil-simple", Write: "pencil-simple", Read: "file-text",
      SendMessage: "chat-circle-text", Agent: "users", Grep: "gear",
    }
    for (const [tool, icon] of Object.entries(names)) expect(toolIcon(tool)).toBe(icon)
    const { container } = render(<ActionCard item={act({ tool: "Read" })} />)
    expect(container.querySelector("svg")?.getAttribute("data-icon")).toBe("file-text")
  })

  it("shows a status dot with a text label", () => {
    const { container, rerender } = render(<ActionCard item={act({ status: "running" })} />)
    expect(container.querySelector(".ag-dot-running")).toBeTruthy()
    expect(screen.getByText("Running")).toBeTruthy()
    rerender(<ActionCard item={act({ status: "ok" })} />)
    expect(container.querySelector(".ag-dot-ok")).toBeTruthy()
    expect(screen.getByText("Done")).toBeTruthy()
    rerender(<ActionCard item={act({ status: "error" })} />)
    expect(container.querySelector(".ag-dot-error")).toBeTruthy()
    expect(screen.getByText("Failed")).toBeTruthy()
  })

  it("expands and collapses by mouse and keyboard", async () => {
    const user = userEvent.setup()
    render(<ActionCard item={act({ excerpt: "all passed" })} />)
    const btn = screen.getByRole("button")
    expect(btn.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByText("all passed")).toBeNull()
    await user.click(btn)
    expect(btn.getAttribute("aria-expanded")).toBe("true")
    expect(screen.getByText("all passed")).toBeTruthy()
    btn.focus()
    await user.keyboard("{Enter}")
    expect(btn.getAttribute("aria-expanded")).toBe("false")
    await user.keyboard(" ")
    expect(btn.getAttribute("aria-expanded")).toBe("true")
  })

  it("clips the excerpt to 6 lines", () => {
    const text = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`).join("\n")
    render(<ActionCard item={act({ excerpt: text })} />)
    fireEvent.click(screen.getByRole("button"))
    const shown = screen.getByTestId("agent-excerpt").textContent ?? ""
    expect(shown.split("\n")).toHaveLength(6)
    expect(shown).toContain("line 6")
    expect(shown).not.toContain("line 7")
  })

  it("groups three or more actions but not two", () => {
    const mk = (n: number) => Array.from({ length: n }, (_, i) => act({ id: `a${i}`, line: i + 1, title: `Step ${i + 1}` }))
    const { unmount } = render(<MessageList items={mk(2)} />)
    expect(screen.getAllByTestId("agent-action")).toHaveLength(2)
    expect(screen.queryByTestId("agent-action-group")).toBeNull()
    unmount()
    render(<MessageList items={mk(3)} />)
    const group = screen.getByTestId("agent-action-group")
    expect(within(group).getByText("3 actions")).toBeTruthy()
    expect(screen.queryAllByTestId("agent-action")).toHaveLength(0)
    const head = within(group).getByRole("button", { name: /3 actions/ })
    fireEvent.click(head)
    expect(screen.getAllByTestId("agent-action")).toHaveLength(3)
    fireEvent.click(head)
    expect(screen.queryAllByTestId("agent-action")).toHaveLength(0)
  })

  it("group opens with Enter", async () => {
    const user = userEvent.setup()
    render(<ActionGroup items={[act({ id: "a" }), act({ id: "b", line: 2 }), act({ id: "c", line: 3 })]} />)
    screen.getByRole("button", { name: /3 actions/ }).focus()
    await user.keyboard("{Enter}")
    expect(screen.getAllByTestId("agent-action")).toHaveLength(3)
  })

  it("an update changes the status in place and clears the working title", () => {
    const { rerender } = render(<MessageList state="working" items={[act({ status: "running" })]} />)
    expect(screen.getByTestId("agent-working").textContent).toContain("Run the tests")
    rerender(<MessageList state="working" items={[act({ status: "error", excerpt: "boom" })]} />)
    expect(screen.getByText("Failed")).toBeTruthy()
    expect(screen.getByTestId("agent-working").textContent).not.toContain("Run the tests")
  })
})
