import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CardActions, type CardAction } from "@/features/agent/blocks/CardActions"
import { mockApi } from "@/test/mockApi"

afterEach(() => { vi.unstubAllGlobals(); window.location.hash = "" })

const install: CardAction = {
  label: "Install", kind: "op", op: { method: "POST", path: "/api/update/install", body: { yes: true, tag: "v9.2" } },
  confirm: "Install v9.2?", danger: true,
}

function show(actions: CardAction[], onNote = vi.fn()) {
  render(<QueryClientProvider client={new QueryClient()}><CardActions actions={actions} onNote={onNote} /></QueryClientProvider>)
  return onNote
}

describe("CardActions", () => {
  it("opens a link in a new tab safely", () => {
    show([{ label: "Docs", kind: "link", href: "https://example.com/x" }])
    const a = screen.getByRole("link", { name: "Docs" })
    expect(a.getAttribute("target")).toBe("_blank")
    expect(a.getAttribute("rel")).toBe("noopener")
  })
  it("navigates on a route button", () => {
    show([{ label: "Open build", kind: "route", route: { to: "p/demo/build", params: { run: "r1" } } }])
    fireEvent.click(screen.getByRole("button", { name: "Open build" }))
    expect(window.location.hash).toBe("#/p/demo/build?run=r1")
  })
  it("asks first, runs the op, then notes the agent once", async () => {
    const { calls } = mockApi({ "POST /api/update/install": { ok: true } })
    const note = show([install])
    fireEvent.click(screen.getByRole("button", { name: "Install" }))
    expect(screen.getByText("Install v9.2?")).toBeTruthy()
    expect(calls).toHaveLength(0)
    fireEvent.click(screen.getAllByRole("button", { name: "Install" }).at(-1)!)
    await waitFor(() => expect(note).toHaveBeenCalledTimes(1))
    expect(note).toHaveBeenCalledWith("[Phoenix panel · button] Install done")
    expect(calls[0]).toMatchObject({ method: "POST", path: "/api/update/install", body: { yes: true, tag: "v9.2" } })
    expect(screen.getByTestId("card-result").textContent).toContain("done")
  })
  it("runs at once without confirm and cancel does nothing", async () => {
    const { calls } = mockApi({ "POST /api/x": {} })
    const note = show([{ label: "Go", kind: "op", op: { method: "POST", path: "/api/x" } }, { ...install }])
    fireEvent.click(screen.getByRole("button", { name: "Go" }))
    await waitFor(() => expect(note).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("button", { name: "Install" }))
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(calls).toHaveLength(1)
  })
  it("shows only the reason on failure, no note", async () => {
    const { failure } = await import("@/test/mockApi")
    mockApi({ "POST /api/x": failure(400, "nothing to do") })
    const note = show([{ label: "Go", kind: "op", op: { method: "POST", path: "/api/x" } }])
    fireEvent.click(screen.getByRole("button", { name: "Go" }))
    await waitFor(() => expect(screen.getByTestId("card-result").textContent).toContain("nothing to do"))
    expect(note).not.toHaveBeenCalled()
  })
  it("renders nothing without actions", () => {
    show([])
    expect(screen.queryByTestId("card-actions")).toBeNull()
  })
})
