import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import { useRef, useState } from "react"

import { AgentPanel } from "@/features/agent/AgentPanel"
import { agentStatus, agentStatuses } from "@/test/fixtures"
import { agentRoutes, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

function Harness() {
  const [open, setOpen] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={opener} onClick={() => setOpen(true)}>opener</button>
      <AgentPanel open={open} onClose={() => setOpen(false)} opener={opener} />
    </>
  )
}

const openIt = () => fireEvent.click(screen.getByText("opener"))
const panel = () => screen.getByLabelText("Phoenix agent panel", { selector: "aside" })

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

test("opens, focuses the message box, and returns focus on close", () => {
  mockApi(agentRoutes())
  renderWithProviders(<Harness />)
  const opener = screen.getByText("opener")
  expect(panel()).not.toHaveClass("open")
  fireEvent.click(opener)
  expect(panel()).toHaveClass("open")
  expect(screen.getByLabelText("Message")).toHaveFocus()
  fireEvent.click(screen.getByRole("button", { name: "Close" }))
  expect(panel()).not.toHaveClass("open")
  expect(opener).toHaveFocus()
})

test("shows the title and the header buttons", () => {
  mockApi(agentRoutes())
  renderWithProviders(<Harness />)
  openIt()
  expect(screen.getByRole("heading", { name: "Phoenix agent" })).toBeInTheDocument()
  for (const name of ["History", "Wide", "Close"]) expect(screen.getByRole("button", { name })).toBeInTheDocument()
})

test("Wide toggles and is remembered", () => {
  mockApi(agentRoutes())
  const first = renderWithProviders(<Harness />)
  openIt()
  const wide = screen.getByRole("button", { name: "Wide" })
  expect(wide).toHaveAttribute("aria-pressed", "false")
  fireEvent.click(wide)
  expect(wide).toHaveAttribute("aria-pressed", "true")
  expect(panel()).toHaveClass("wide")
  first.unmount()
  renderWithProviders(<Harness />)
  openIt()
  expect(screen.getByRole("button", { name: "Wide" })).toHaveAttribute("aria-pressed", "true")
  fireEvent.click(screen.getByRole("button", { name: "Wide" }))
  expect(panel()).not.toHaveClass("wide")
})

test("works when localStorage throws", () => {
  mockApi(agentRoutes())
  const boom = () => { throw new Error("blocked") }
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom)
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom)
  renderWithProviders(<Harness />)
  openIt()
  fireEvent.click(screen.getByRole("button", { name: "Wide" }))
  expect(panel()).toHaveClass("wide")
  vi.restoreAllMocks()
})

test.each([
  ["idle", "Idle"],
  ["working", "Working…"],
  ["asleep", "Asleep"],
] as const)("status pill for %s", async (state, text) => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses[state] })
  renderWithProviders(<Harness />)
  expect(await screen.findByText(text)).toBeInTheDocument()
})

test("status pill for queued shows a count", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatuses.queued })
  renderWithProviders(<Harness />)
  expect(await screen.findByTestId("agent-state")).toHaveTextContent(/^Queued \d+$/)
})

test("the Claude app link shows only with app_url", async () => {
  mockApi({ ...agentRoutes(), "GET /api/agent": agentStatus("idle", { app_url: "https://claude.ai/code/x" }) })
  const first = renderWithProviders(<Harness />)
  openIt()
  const link = await screen.findByRole("link", { name: "Open in Claude app" })
  expect(link).toHaveAttribute("href", "https://claude.ai/code/x")
  expect(link).toHaveAttribute("target", "_blank")
  expect(link).toHaveAttribute("rel", "noopener noreferrer")
  first.unmount()
  mockApi(agentRoutes())
  renderWithProviders(<Harness />)
  openIt()
  await screen.findByText("Idle")
  expect(screen.queryByRole("link", { name: "Open in Claude app" })).toBeNull()
})

test("the panel is marked hidden while closed", async () => {
  mockApi(agentRoutes())
  renderWithProviders(<Harness />)
  expect(panel()).toHaveAttribute("aria-hidden", "true")
  await act(async () => {})
  await waitFor(() => expect(screen.getByText("Idle")).toBeInTheDocument())
})

test("the drawer shows no Suggestions strip, even when there are suggestions", async () => {
  const suggestion = { key: "k1", text: "Fill in empty keys", section: "x", attention: false, shown: false }
  const { calls } = mockApi({ ...agentRoutes(), "GET /api/suggest": { mode: "on", suggestions: [suggestion] } })
  renderWithProviders(<Harness />)
  openIt()
  await screen.findByText("Idle")
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggest")).toBe(true))
  expect(screen.queryByText("Suggestions")).toBeNull()
  expect(screen.queryByRole("region", { name: "Suggestions" })).toBeNull()
  expect(screen.queryByText("Fill in empty keys")).toBeNull()
})

test("while open the page behind is locked; closing and unmounting unlock it", () => {
  mockApi(agentRoutes())
  const view = renderWithProviders(<Harness />)
  expect(document.body).not.toHaveClass("agent-open")
  openIt()
  expect(document.body).toHaveClass("agent-open")
  fireEvent.click(screen.getByRole("button", { name: "Close" }))
  expect(document.body).not.toHaveClass("agent-open")
  openIt()
  expect(document.body).toHaveClass("agent-open")
  view.unmount()
  expect(document.body).not.toHaveClass("agent-open")
})

test("on a phone the panel takes the height above the keyboard and stops listening on close", () => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("max-width: 719px"), media: q, addEventListener() {}, removeEventListener() {} }))
  const listeners = new Set<() => void>()
  const vv = {
    height: 400, offsetTop: 0,
    addEventListener: (_: string, f: () => void) => listeners.add(f),
    removeEventListener: (_: string, f: () => void) => listeners.delete(f),
  }
  vi.stubGlobal("visualViewport", vv)
  mockApi(agentRoutes())
  renderWithProviders(<Harness />)
  openIt()
  expect(panel().style.getPropertyValue("--ag-vh")).toBe("340px")
  vv.height = 300
  act(() => listeners.forEach((f) => f()))
  expect(panel().style.getPropertyValue("--ag-vh")).toBe("240px")
  fireEvent.click(screen.getByRole("button", { name: "Close" }))
  expect(listeners.size).toBe(0)
  expect(panel().style.getPropertyValue("--ag-vh")).toBe("")
})
