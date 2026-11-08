import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { mockApi } from "@/test/mockApi"
import { row } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

import { ProjectsBody } from "./ProjectsBody"

const pr = { number: 7, title: "Add x", url: "https://github.com/o/r/pull/7" }
const data = {
  top: [{ ...row({ name: "alpha", repo: "o/alpha", repo_owner: "o", repo_name: "alpha" }), needs_merge: true, pr }],
  rest: [{ ...row({ name: "beta" }), needs_merge: false, pr: null }], total: 2,
}

describe("ProjectsBody", () => {
  it("shows a tile per project and a PR link only when one waits", () => {
    mockApi({})
    renderWithProviders(<ProjectsBody type="projects" data={data} />)
    expect(screen.getByRole("link", { name: "alpha" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "beta" })).toBeTruthy()
    const link = screen.getByRole("link", { name: /PR #7 waiting to merge/ })
    expect(link.getAttribute("href")).toBe(pr.url)
    expect(screen.getAllByText(/waiting to merge/)).toHaveLength(1)
    expect(screen.queryByText("Remove")).toBeNull()
  })

  it("says so when no project matches", () => {
    mockApi({})
    renderWithProviders(<ProjectsBody type="projects" data={{ top: [], rest: [], total: 0 }} />)
    expect(screen.getByTestId("projects-empty")).toBeTruthy()
  })
})
