import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"

import { failure, mockApi } from "@/test/mockApi"

import { RunDocs } from "./RunDocs"

afterEach(() => vi.unstubAllGlobals())

function show(list: unknown) {
  const api = mockApi({ "GET /api/docs/list": list })
  render(<QueryClientProvider client={new QueryClient()}><RunDocs runId="r1" /></QueryClientProvider>)
  return api
}

it("shows View and Download only for plan.md and summary.md", async () => {
  show([
    { id: "run:r1/plan.md", title: "plan.md", size: 10 },
    { id: "run:r1/summary.md", title: "summary.md", size: 10 },
    { id: "run:r1/notes.txt", title: "notes.txt", size: 10 },
  ])
  await waitFor(() => expect(screen.getByTestId("run-docs")).toBeTruthy())
  expect(screen.getAllByRole("link", { name: /View/ })).toHaveLength(2)
  expect(screen.getAllByRole("link", { name: /Download/ })).toHaveLength(2)
  expect(screen.queryByText("notes.txt")).toBeNull()
})

it("renders nothing when the list is empty", async () => {
  const api = show([])
  await waitFor(() => expect(api.calls.length).toBe(1))
  expect(screen.queryByTestId("run-docs")).toBeNull()
})

it("renders nothing when the request fails", async () => {
  const api = show(failure(500, "boom"))
  await waitFor(() => expect(api.calls.length).toBe(1))
  expect(screen.queryByTestId("run-docs")).toBeNull()
})
