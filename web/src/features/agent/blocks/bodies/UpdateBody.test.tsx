import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { UpdateStatus } from "@/lib/types"

import { UpdateBody } from "./UpdateBody"

const base = { supported: true, installed: { tag: "v1.0", commit: "abc" }, newest: "v1.1", update_available: true, running: false } as unknown as UpdateStatus

describe("UpdateBody", () => {
  it("shows current and available version", () => {
    render(<UpdateBody type="update" data={base} />)
    expect(screen.getByTestId("update-current").textContent).toBe("v1.0")
    expect(screen.getByTestId("update-available").textContent).toBe("v1.1")
    expect(screen.getByTestId("update-status").textContent).toContain("available")
  })

  it("says up to date", () => {
    render(<UpdateBody type="update" data={{ ...base, update_available: false }} />)
    expect(screen.getByTestId("update-available").textContent).toBe("none")
    expect(screen.getByTestId("update-status").textContent).toBe("Up to date.")
  })
})
