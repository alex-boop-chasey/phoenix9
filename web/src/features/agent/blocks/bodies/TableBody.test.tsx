import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { TableBody } from "./TableBody"

describe("TableBody", () => {
  it("renders headers, cells, a scrolling wrapper and the footer", () => {
    render(<TableBody type="table" data={{ columns: ["Name", "N"], rows: [["a", 1], ["b", 2]], footer: "proposed by the agent" }} />)
    expect(screen.getAllByRole("columnheader").map((e) => e.textContent)).toEqual(["Name", "N"])
    expect(screen.getAllByRole("row")).toHaveLength(3)
    expect(screen.getByRole("region").className).toContain("overflow-x-auto")
    expect(screen.getByTestId("card-footer")).toBeTruthy()
  })
})
