import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ChartBody } from "./ChartBody"

const series = [{ label: "Mon", value: 2 }, { label: "Tue", value: 4 }, { label: "Wed", value: 3 }]

describe("ChartBody", () => {
  it("draws bars with an accessible label and a hidden value list", () => {
    render(<ChartBody type="chart" data={{ kind: "bars", series }} />)
    expect(screen.getByRole("img", { name: "Bar chart of 3 values" })).toBeTruthy()
    expect(screen.getAllByTestId("bar")).toHaveLength(3)
    expect(screen.getAllByRole("listitem").map((e) => e.textContent)).toEqual(["Mon: 2", "Tue: 4", "Wed: 3"])
    expect(screen.getByTestId("card-footer").textContent).toBe("proposed by the agent")
  })

  it("draws a sparkline", () => {
    render(<ChartBody type="chart" data={{ kind: "spark", series }} />)
    expect(screen.getByRole("img", { name: "Line chart of 3 values" })).toBeTruthy()
    expect(screen.getByTestId("spark-line").getAttribute("points")?.split(" ")).toHaveLength(3)
  })
})
