import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { DiffBody } from "./DiffBody"

const files = [{ name: "a.txt", added: 1, removed: 1, lines: ["diff --git a/a.txt b/a.txt", "@@ -1 +1 @@", "-old", "+new"] }]

describe("DiffBody", () => {
  it("renders the shared diff view", () => {
    render(<DiffBody type="diff" data={{ files, truncated: true }} />)
    expect(screen.getByTestId("diff")).toBeTruthy()
    expect(screen.getByText("+new").className).toContain("bg-ok")
    expect(screen.getByTestId("diff-truncated")).toBeTruthy()
  })

  it("says so when empty", () => {
    render(<DiffBody type="diff" data={{ files: [] }} />)
    expect(screen.getByTestId("diff-empty")).toBeTruthy()
  })
})
