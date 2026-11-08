import { render, screen } from "@testing-library/react"
import { expect, it } from "vitest"

import { DocButtons } from "./DocButtons"

it("View opens the doc page in a new tab and Download points at the API", () => {
  render(<DocButtons id="run:r1/summary.md" />)
  const view = screen.getByRole("link", { name: /View/ })
  expect(view.getAttribute("href")).toBe("#/doc?path=run%3Ar1%2Fsummary.md")
  expect(view.getAttribute("target")).toBe("_blank")
  expect(view.getAttribute("rel")).toBe("noopener")
  expect(screen.getByRole("link", { name: /Download/ }).getAttribute("href")).toContain("docs/download?id=run%3Ar1%2Fsummary.md")
})
