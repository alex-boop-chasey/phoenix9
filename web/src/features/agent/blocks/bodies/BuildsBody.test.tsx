import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { BUILDS } from "@/test/buildFixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { BuildsBody } from "./BuildsBody"

describe("BuildsBody", () => {
  it("lists each build with a link that opens its run", () => {
    mockApi({})
    renderWithProviders(<BuildsBody type="builds" data={BUILDS} />)
    const link = screen.getByRole("link", { name: "r-wait" })
    expect(link.getAttribute("href")).toBe("/p/demo-site/build?run=r-wait")
    expect(screen.getAllByRole("listitem")).toHaveLength(BUILDS.length)
  })

  it("says so when there are no builds", () => {
    mockApi({})
    renderWithProviders(<BuildsBody type="builds" data={[]} />)
    expect(screen.getByTestId("builds-empty")).toBeTruthy()
  })
})
