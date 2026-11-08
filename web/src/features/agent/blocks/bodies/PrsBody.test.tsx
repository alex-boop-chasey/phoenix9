import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PrsBody } from "./PrsBody"

const row = { project: "a", number: 7, title: "Fix it", draft: true, checks: "passing", url: "https://github.com/o/r/pull/7", updated_at: "2020-01-01T00:00:00Z" }

describe("PrsBody", () => {
  it("shows number, title, badges and link", () => {
    render(<PrsBody type="prs" data={[row]} />)
    expect(screen.getByRole("link", { name: "#7 Fix it" }).getAttribute("href")).toBe(row.url)
    expect(screen.getByTestId("pr-draft")).toBeTruthy()
    expect(screen.getByTestId("pr-checks").textContent).toBe("passing")
  })

  it("does not link a non-web address", () => {
    render(<PrsBody type="prs" data={[{ ...row, url: "javascript:alert(1)" }]} />)
    expect(screen.queryByRole("link")).toBeNull()
  })

  it("says so when empty", () => {
    render(<PrsBody type="prs" data={[]} />)
    expect(screen.getByTestId("prs-empty")).toBeTruthy()
  })
})
