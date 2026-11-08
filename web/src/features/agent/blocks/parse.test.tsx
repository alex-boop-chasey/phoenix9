import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render as rtlRender, screen, waitFor } from "@testing-library/react"
import type { ReactElement, ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { clearBlockCache } from "@/features/agent/blocks/BlockView"
import { parseBlocks } from "@/features/agent/blocks/parse"
import { AgentMessage, MessageList } from "@/features/agent/messages"
import { ActionCard } from "@/features/agent/ActionCard"
import type { AgentItem } from "@/features/agent/useAgent"

const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
const render = (ui: ReactElement) => rtlRender(ui, { wrapper })

const card = '{"v":1,"type":"prs"}'
const md = (json = card, fallback = "Open PRs: see the dashboard.") => `Before\n\n\`\`\`phoenix-card\n${json}\n\`\`\`\n${fallback}\n\nAfter`

function mockCheck(result: { ok: boolean; reason?: string | null }) {
  const fn = vi.fn(async (_url?: unknown) => new Response(JSON.stringify({ ok: true, data: { ok: result.ok, reason: result.reason ?? null, resolved: null } }), { status: 200 }))
  vi.stubGlobal("fetch", fn)
  return fn
}

beforeEach(() => clearBlockCache())
afterEach(() => vi.unstubAllGlobals())

describe("parseBlocks", () => {
  it("splits text, block and fallback", () => {
    const parts = parseBlocks(md())
    expect(parts.map((p) => p.type)).toEqual(["text", "block", "text"])
    expect(parts[1]).toMatchObject({ kind: "card", json: card, fallback: "Open PRs: see the dashboard." })
    expect(parts[2]).toMatchObject({ text: "\nAfter" })
  })
  it("keeps ordinary code fences as text and flags unknown tags", () => {
    expect(parseBlocks("```ts\nx\n```")).toEqual([{ type: "text", text: "```ts\nx\n```" }])
    const p = parseBlocks("```phoenix-foo\n{}\n```")[0]
    expect(p).toMatchObject({ type: "block", kind: null })
  })
  it("maps all four kinds and handles a missing fallback", () => {
    const kinds = ["card", "choice", "confirm", "nav"].map((k) => (parseBlocks(`\`\`\`phoenix-${k}\n{}\n\`\`\``)[0] as { kind: string }).kind)
    expect(kinds).toEqual(["card", "choice", "confirm", "nav"])
    expect((parseBlocks("```phoenix-nav\n{}\n```")[0] as { fallback: string }).fallback).toBe("")
  })
  it("leaves an unclosed fence as text", () => {
    expect(parseBlocks("```phoenix-card\n{}")[0]?.type).toBe("text")
  })
})

describe("AgentMessage blocks", () => {
  it("hides the fallback when the block renders, and checks once", async () => {
    const fn = mockCheck({ ok: true })
    const { rerender } = render(<AgentMessage markdown={md()} />)
    await waitFor(() => expect(screen.getByTestId("block-card")).toBeTruthy())
    expect(screen.queryByText(/see the dashboard/)).toBeNull()
    rerender(<AgentMessage markdown={md()} />)
    expect(fn.mock.calls.filter((c) => String(c[0]).includes("blocks/check"))).toHaveLength(1)
  })
  it("shows fallback and reason when the check fails", async () => {
    mockCheck({ ok: false, reason: "bad type" })
    render(<AgentMessage markdown={md()} />)
    await waitFor(() => expect(screen.getByText("block could not be shown: bad type")).toBeTruthy())
    expect(screen.getByText(/see the dashboard/)).toBeTruthy()
  })
  it("shows fallback when the request fails or the tag is unknown", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down") }))
    const { unmount } = render(<AgentMessage markdown={md()} />)
    await waitFor(() => expect(screen.getByText(/block could not be shown/)).toBeTruthy())
    unmount()
    render(<AgentMessage markdown={"```phoenix-foo\n{}\n```\nPlain words."} />)
    expect(screen.getByText("Plain words.")).toBeTruthy()
    expect(screen.getByText(/unknown block type phoenix-foo/)).toBeTruthy()
  })
  it("marks frozen blocks with an as-of line", async () => {
    mockCheck({ ok: true })
    render(<AgentMessage markdown={md()} frozen at="2026-11-07T14:00:00" />)
    await waitFor(() => expect(screen.getByText(/^as of /)).toBeTruthy())
    expect(screen.getByTestId("block-card").getAttribute("data-frozen")).toBe("true")
  })
})

describe("who may show blocks", () => {
  it("MessageList freezes items before the latest divider", async () => {
    mockCheck({ ok: true })
    const items: AgentItem[] = [
      { type: "agent", line: 1, markdown: md(), at: "2026-11-07T14:00:00" },
      { type: "session", line: 2, session_id: "s2" },
      { type: "agent", line: 3, markdown: md('{"v":1,"type":"prs","title":"x"}'), at: "2026-11-07T15:00:00" },
    ]
    render(<MessageList items={items} state="idle" />)
    await waitFor(() => expect(screen.getAllByTestId("block-card")).toHaveLength(2))
    const [old, fresh] = screen.getAllByTestId("block-card")
    expect(old?.getAttribute("data-frozen")).toBe("true")
    expect(fresh?.getAttribute("data-frozen")).toBeNull()
  })
  it("user bubbles and action excerpts show fences as plain code", () => {
    const fn = mockCheck({ ok: true })
    const items: AgentItem[] = [{ type: "user", line: 1, text: md(), origin: "panel", at: "2026-11-07T14:00:00" }]
    render(<MessageList items={items} state="idle" />)
    render(<ActionCard item={{ type: "action", line: 2, id: "a", tool: "Bash", title: "t", input_summary: "", status: "ok", excerpt: md() }} />)
    expect(screen.queryByTestId("block-card")).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })
})
