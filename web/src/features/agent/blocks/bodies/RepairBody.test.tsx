import { fireEvent, screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

import { RepairBody } from "./RepairBody"

const NOTE = "# Repair r1\n\nWhy: fix\n\n## Steps\n- retry task 1\n"
const data = {
  run_id: "r1", status_line: "The run is failed; the check found 1 problem.",
  findings: [{ code: "x", text: "Task 1 is odd", task: 1 }],
  note: { name: "1-fix.md", text: NOTE, dry_run: { ok: true, steps: ["retry task 1"], refused: null, check_after: [], would_roll_back: false } },
}

describe("RepairBody", () => {
  it("shows summary, findings, note and dry run", () => {
    mockApi({})
    renderWithProviders(<RepairBody type="repair" data={data} />)
    expect(screen.getByTestId("repair-status").textContent).toContain("1 problem")
    expect(screen.getByText("Task 1 is odd")).toBeTruthy()
    expect(screen.getByTestId("repair-note").textContent).toContain("retry task 1")
    expect(screen.getByTestId("repair-dry").textContent).toContain("went fine")
  })

  it("asks to confirm, then posts the note", async () => {
    const { calls } = mockApi({ "POST /api/repair/r1/apply": { ok: true } })
    renderWithProviders(<RepairBody type="repair" data={data} />)
    fireEvent.click(screen.getByRole("button", { name: "Apply" }))
    expect(calls.length).toBe(0)
    await screen.findByText("Apply this repair?")
    fireEvent.click(screen.getAllByRole("button", { name: "Apply" }).at(-1)!)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]?.body).toEqual({ note: NOTE })
    expect((await screen.findByTestId("repair-result")).textContent).toContain("applied")
  })

  it("edits the note and re-runs the dry run on save", async () => {
    const { calls } = mockApi({
      "POST /api/repair/r1/apply": { ok: false, dry_run: true, refused: "no such task", steps: [] },
    })
    renderWithProviders(<RepairBody type="repair" data={data} />)
    fireEvent.click(screen.getByRole("button", { name: "Edit" }))
    const box = screen.getByLabelText("Repair note")
    fireEvent.change(box, { target: { value: NOTE + "- retry task 9\n" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(screen.getByTestId("repair-dry").textContent).toContain("refused"))
    expect(calls[0]?.body).toEqual({ note: NOTE + "- retry task 9\n", dry_run: true })
    expect(screen.getByTestId("repair-note").textContent).toContain("task 9")
  })

  it("has no buttons when frozen", () => {
    mockApi({})
    renderWithProviders(<RepairBody type="repair" data={data} frozen />)
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull()
  })
})
