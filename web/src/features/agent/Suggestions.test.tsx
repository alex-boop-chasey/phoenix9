import { fireEvent, screen, waitFor } from "@testing-library/react"

import { Suggestions } from "@/features/agent/Suggestions"
import { agentRoutes, mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

const item = (key: string, text: string) => ({ key, text, section: "x", attention: false, shown: false })
const routes = (list: unknown[]) => ({ ...agentRoutes(), "GET /api/suggest": { mode: "on", suggestions: list } })

test("collapsed when there is nothing to suggest", async () => {
  const { calls } = mockApi(routes([]))
  renderWithProviders(<Suggestions />)
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggest")).toBe(true))
  expect(screen.queryByTestId("agent-suggestions")).toBeNull()
})

test("Ask, Snooze and Dismiss act on one line; the report link opens the Logs viewer", async () => {
  const { calls } = mockApi({
    ...routes([item("k1", "Update is ready")]),
    "POST /api/suggest/k1/snooze": { ok: true },
    "POST /api/suggest/k1/dismiss": { ok: true },
    "POST /api/agent/send": { sent: true, at: "", after_line: 1 },
  })
  renderWithProviders(<Suggestions />)
  expect(await screen.findByText("Update is ready")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Full report" })).toHaveAttribute("href", expect.stringContaining("/logs?log=reports"))
  fireEvent.click(screen.getByRole("button", { name: "Ask" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/agent/send")).toBe(true))
  fireEvent.click(screen.getByRole("button", { name: "Snooze 1 day" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggest/k1/snooze")).toBe(true))
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggest/k1/dismiss")).toBe(true))
})
