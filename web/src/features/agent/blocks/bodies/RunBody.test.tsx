import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { runDetail } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { RunBody } from "./RunBody"

describe("RunBody", () => {
  it("shows the Build tab's step list", () => {
    mockApi({})
    renderWithProviders(<RunBody type="run" data={runDetail()} />)
    expect(screen.getByText("At the start")).toBeTruthy()
    expect(screen.getByText("At the end")).toBeTruthy()
  })

  it("does not break on data without steps", () => {
    mockApi({})
    renderWithProviders(<RunBody type="run" data={{}} />)
    expect(screen.getByText(/no steps/)).toBeTruthy()
  })
})
