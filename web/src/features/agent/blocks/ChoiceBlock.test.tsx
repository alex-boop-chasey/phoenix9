import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ChoiceBlock } from "@/features/agent/blocks/ChoiceBlock"
import { agentRoutes, mockApi } from "@/test/mockApi"

afterEach(() => vi.unstubAllGlobals())

const block = (over: object = {}) => JSON.stringify({
  v: 1, id: "pick-1", question: "Which way?", mode: "single",
  options: [
    { key: "a", label: "Alpha", detail: "the first", recommended: true },
    { key: "b", label: "Beta" },
    { key: "c", label: "Gamma" },
  ], ...over,
})

function show(json: string, props: { frozen?: boolean; later?: string[] } = {}) {
  const api = mockApi({ ...agentRoutes(), "POST /api/agent/send": { sent: true, at: "", after_line: 1 } })
  render(<QueryClientProvider client={new QueryClient()}><ChoiceBlock json={json} {...props} /></QueryClientProvider>)
  const sent = () => api.calls.filter((c) => c.method === "POST" && c.path.endsWith("agent/send"))
  return { sent }
}

describe("ChoiceBlock", () => {
  it("shows tiles, detail and the Recommended pill", () => {
    show(block())
    expect(screen.getByText("Which way?")).toBeTruthy()
    expect(screen.getByText("the first")).toBeTruthy()
    expect(screen.getAllByText("Recommended")).toHaveLength(1)
    expect(screen.getAllByRole("radio")).toHaveLength(3)
  })
  it("single mode sends once on click, then reads You chose", async () => {
    const { sent } = show(block())
    fireEvent.click(screen.getByRole("radio", { name: /Beta/ }))
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · choice pick-1] Beta" })
    expect(screen.getByTestId("choice-answer").textContent).toBe("You chose: Beta")
    fireEvent.click(screen.getByRole("radio", { name: /Gamma/ }))
    expect(sent()).toHaveLength(1)
  })
  it("multi mode needs the Send button and joins labels", async () => {
    const { sent } = show(block({ mode: "multi" }))
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement
    expect(send.disabled).toBe(true)
    fireEvent.click(screen.getByRole("checkbox", { name: /Alpha/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /Gamma/ }))
    expect(sent()).toHaveLength(0)
    fireEvent.click(send)
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · choice pick-1] Alpha, Gamma" })
  })
  it("sends the Other text with the other marker", async () => {
    const { sent } = show(block({ other: true }))
    fireEvent.change(screen.getByLabelText("Other:"), { target: { value: "Delta" } })
    fireEvent.keyDown(screen.getByLabelText("Other:"), { key: "Enter" })
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0]!.body).toEqual({ text: "[Phoenix panel · choice pick-1 · other] Delta" })
    expect(screen.getByTestId("choice-answer").textContent).toBe("You chose: Delta")
  })
  it("moves between tiles with the arrow keys", () => {
    show(block())
    const [a, b] = screen.getAllByRole("radio")
    a!.focus()
    fireEvent.keyDown(a!, { key: "ArrowDown" })
    expect(document.activeElement).toBe(b)
    fireEvent.keyDown(b!, { key: "ArrowUp" })
    expect(document.activeElement).toBe(a)
  })
  it("is answered when a later user item says so", () => {
    const { sent } = show(block(), { later: ["hi", "[Phoenix panel · choice pick-1] Gamma"] })
    expect(screen.getByTestId("choice-answer").textContent).toBe("You chose: Gamma")
    fireEvent.click(screen.getByRole("radio", { name: /Beta/ }))
    expect(sent()).toHaveLength(0)
  })
  it("ignores answers to other choices", () => {
    show(block(), { later: ["[Phoenix panel · choice pick-12] Gamma"] })
    expect(screen.queryByTestId("choice-answer")).toBeNull()
  })
  it("is read-only when frozen", () => {
    const { sent } = show(block(), { frozen: true })
    fireEvent.click(screen.getByRole("radio", { name: /Beta/ }))
    expect(sent()).toHaveLength(0)
  })
})
