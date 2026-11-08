import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SettingsPreviewBody } from "./SettingsPreviewBody"

const data = {
  rows: [
    { key: "a.b", before: 1, after: 2, ok: true, reason: null },
    { key: "c", before: null, after: "x", ok: false, reason: "not a valid value" },
  ],
  footer: "proposed by the agent",
}

describe("SettingsPreviewBody", () => {
  it("shows before and after and a reason only for rows that are not ok", () => {
    render(<SettingsPreviewBody type="settings-preview" data={data} />)
    expect(screen.getAllByTestId("before").map((e) => e.textContent)).toEqual(["1", "(not set)"])
    expect(screen.getAllByTestId("after").map((e) => e.textContent)).toEqual(["2", "x"])
    expect(screen.getAllByTestId("reason")).toHaveLength(1)
    expect(screen.getByText("not a valid value")).toBeTruthy()
    expect(screen.getByTestId("card-footer").textContent).toBe("proposed by the agent")
  })
})
