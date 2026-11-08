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

  it("says so when nothing waits", () => {
    mockApi({})
    renderWithProviders(<GatesBody type="gates" data={[]} />)
    expect(screen.getByTestId("gates-empty")).toBeTruthy()
  })
})
