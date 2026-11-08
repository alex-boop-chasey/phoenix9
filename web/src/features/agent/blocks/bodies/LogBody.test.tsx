import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { LogBody } from "./LogBody"

describe("LogBody", () => {
  it("shows lines", () => {
    render(<LogBody type="log" data={{ lines: ["one", "two"], truncated: false }} />)
    expect(screen.getByTestId("log-lines").textContent).toBe("one\ntwo")
    expect(screen.queryByTestId("log-truncated")).toBeNull()
  })

  it("caps at 200 and says so", () => {
    const lines = Array.from({ length: 250 }, (_, i) => `l${i}`)
    render(<LogBody type="log" data={{ lines, truncated: false }} />)
    expect(screen.getByTestId("log-truncated").textContent).toBe("showing the last 200 lines")
    expect(screen.getByTestId("log-lines").textContent?.startsWith("l50")).toBe(true)
  })
})
