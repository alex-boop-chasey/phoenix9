import { act, fireEvent, screen } from "@testing-library/react"
import { useRef, useState } from "react"

import { AgentPanel } from "@/features/agent/AgentPanel"
import { navigateKeepingPanel } from "@/features/agent/navigate"
import { useUiGo } from "@/features/agent/uiGo"
import { useLiveEvents } from "@/lib/live"
import { agentRoutes, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

class FakeEventSource {
  static last: FakeEventSource | null = null
  onopen: (() => void) | null = null
  onmessage: ((m: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  listeners: Record<string, ((m: MessageEvent) => void)[]> = {}
  constructor(public url: string) {
    if (url.includes("api/events")) FakeEventSource.last = this
  }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(fn)
  }
  close() {}
  emit(type: string, data: object) {
    const m = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: "" })
    this.listeners[type]?.forEach((f) => f(m))
  }
}

function Harness() {
  const [open, setOpen] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  const go = useUiGo(open)
  useLiveEvents(undefined, go.onEvent)
  return (
    <>
      <button onClick={() => setOpen(!open)}>toggle</button>
      <AgentPanel open={open} onClose={() => setOpen(false)} opener={opener} moved={go.moved} onBack={go.back} />
    </>
  )
}

const uiGo = (hash: string, label: string) => ({
  id: 1, ts: "", type: "ui.go", project: null, run: null, task: null, step: null, data: { hash, label, by: "agent" },
})

beforeEach(() => {
  window.localStorage.clear()
  window.location.hash = "#/start"
  vi.stubGlobal("EventSource", FakeEventSource)
  mockApi(agentRoutes())
})
afterEach(() => vi.unstubAllGlobals())

test("open panel: navigates, shows the line, and Back returns", () => {
  renderWithProviders(<Harness />)
  fireEvent.click(screen.getByText("toggle"))
  act(() => FakeEventSource.last!.emit("ui.go", uiGo("#/settings?section=models", "Settings › Models")))
  expect(window.location.hash).toBe("#/settings?section=models")
  expect(screen.getByTestId("agent-moved")).toHaveTextContent("Moved to Settings › Models")
  expect(screen.getByLabelText("Phoenix agent panel", { selector: "aside" })).toHaveClass("open")
  fireEvent.click(screen.getByRole("button", { name: "Back" }))
  expect(window.location.hash).toBe("#/start")
  expect(screen.queryByTestId("agent-moved")).toBeNull()
})

test("closed panel: the event is ignored", () => {
  renderWithProviders(<Harness />)
  act(() => FakeEventSource.last!.emit("ui.go", uiGo("#/new", "New project")))
  expect(window.location.hash).toBe("#/start")
  expect(screen.queryByTestId("agent-moved")).toBeNull()
})

test("navigateKeepingPanel sets the hash", () => {
  navigateKeepingPanel("#/new")
  expect(window.location.hash).toBe("#/new")
})
