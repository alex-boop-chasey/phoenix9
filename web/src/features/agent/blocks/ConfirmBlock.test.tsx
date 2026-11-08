import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ConfirmBlock } from "@/features/agent/blocks/ConfirmBlock"
import { agentRoutes, mockApi } from "@/test/mockApi"

afterEach(() => vi.unstubAllGlobals())

const block = (over: object = {}) => JSON.stringify({ v: 1, id: "go-1", action: "Delete the branch", command: "phoenix rm x --yes", ...over })

function show(json: string, props: { frozen?: boolean; later?: string[] } = {}) {
  const api = mockApi({ ...agentRoutes(), "POST /api/agent/send": { sent: true, at: "", after_line: 1 } })
  render(<QueryClientProvider client={new QueryClient()}><ConfirmBlock json={json} {...props} /></QueryClientProvider>)
  return () => api.calls.filter((c) => c.method === "POST" && c.path.endsWith("agent/send"))
}

describe("ConfirmBlock", () => {
  it("shows the action and the exact command", () => {
    show(block())
    expect(screen.getByText("Delete the branch")).toBeTruthy()
    expect(screen.getByTestId("confirm-command").textContent).toBe("phoenix rm x --yes")
  })
  it("Yes sends once and becomes read-only", async () => {
    const sent = show(block())
    fireEvent.click(screen.getByRole("button", { name: "Yes, do it" }))
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · confirm go-1] yes" })
    fireEvent.click(screen.getByRole("button", { name: "No" }))
    expect(sent()).toHaveLength(1)
  })
  it("No sends no", async () => {
    const sent = show(block())
    fireEvent.click(screen.getByRole("button", { name: "No" }))
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · confirm go-1] no" })
  })
  it("Other sends the typed text", async () => {
    const sent = show(block())
    fireEvent.change(screen.getByLabelText("Other:"), { target: { value: "later" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · confirm go-1 · other] later" })
  })
  it("marks danger", () => {
    show(block({ danger: true }))
    expect(screen.getByRole("button", { name: "Yes, do it" }).className).toContain("ag-tile-danger")
  })
  it("is read-only when frozen or answered later", () => {
    show(block(), { later: ["[Phoenix panel · confirm go-1] no"] })
    expect((screen.getByRole("button", { name: "No" }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId("confirm-answer").textContent).toBe("You answered: no")
  })
  it("is read-only when frozen", () => {
    show(block(), { frozen: true })
    expect((screen.getByRole("button", { name: "Yes, do it" }) as HTMLButtonElement).disabled).toBe(true)
  })
})
