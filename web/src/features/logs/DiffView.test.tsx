import { render, screen } from "@testing-library/react"

import { DiffView } from "@/features/logs/DiffView"

const DIFF = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n context\n-old\n+new"

describe("DiffView", () => {
  it("added and removed lines styled", () => {
    render(<DiffView text={DIFF} />)
    expect(screen.getByText("+new").className).toContain("bg-ok")
    expect(screen.getByText("-old").className).toContain("bg-bad")
    expect(screen.getByText("context").className).not.toContain("bg-")
  })

  it("hunk headers styled", () => {
    render(<DiffView text={DIFF} />)
    expect(screen.getByText("@@ -1,2 +1,2 @@").className).toContain("bg-info")
  })

  it("file headers shown as titles", () => {
    render(<DiffView text={DIFF} />)
    expect(screen.getByText("diff --git a/a.txt b/a.txt").className).toContain("font-bold")
    expect(screen.getByText("+++ b/a.txt").className).toContain("font-bold")
    expect(screen.getByText("--- a/a.txt").className).not.toContain("bg-bad")
  })

  it("plain text not treated as diff", () => {
    render(<DiffView text={"- a list item\n+ another"} />)
    expect(screen.queryByTestId("diff")).toBeNull()
    expect(screen.getByText(/a list item/).className).not.toContain("bg-")
  })
})
