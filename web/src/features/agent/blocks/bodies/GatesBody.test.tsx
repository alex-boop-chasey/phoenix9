import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { gate } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { GatesBody } from "./GatesBody"

describe("GatesBody", () => {
  it("shows a Needs-you card per open question", () => {
    mockApi({})
    renderWithProviders(<GatesBody type="gates" data={[gate, { ...gate, id: "g2", title: "Second" }]} />)
    expect(screen.getAllByRole("article")).toHaveLength(2)
  })

  it("frozen cards are read-only: no answer buttons", () => {
    const api = mockApi({})
    renderWithProviders(<GatesBody type="gates" data={[gate]} frozen />)
    expect(screen.getAllByRole("article")).toHaveLength(1)
    expect(screen.queryAllByRole("button")).toHaveLength(0)
    expect(screen.getByTestId("need-readonly")).toBeTruthy()
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0)
  })

  it("live cards still have answer buttons", () => {
    mockApi({})
    renderWithProviders(<GatesBody type="gates" data={[gate]} />)
    expect(screen.queryAllByRole("button").length).toBeGreaterThan(0)
  })

  it("says so when nothing waits", () => {
    mockApi({})
    renderWithProviders(<GatesBody type="gates" data={[]} />)
    expect(screen.getByTestId("gates-empty")).toBeTruthy()
  })
})
