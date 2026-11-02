import { fireEvent, screen, waitFor } from "@testing-library/react"

import { MergeReview } from "@/features/gates/MergeReview"
import type { Gate, GateReview } from "@/lib/types"
import { gate as escalation } from "@/test/fixtures"
import { mockApi } from "@/test/mockApi"
import { renderWithProviders } from "@/test/render"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), info: vi.fn(), error: vi.fn() }) }))

const gate: Gate = { ...escalation, id: "r.1", kind: "merge", title: "Merge Tiny?", actions: ["approve", "back", "skip", "stop"] }

const review: GateReview = {
  gate: "r.1", run: "r", project: "alpha", title: "Merge Tiny?", why: "", answered: false,
  summary: "Adds a thing.", tasks: { passed: 3, total: 4, retried: [{ number: 3, title: "T", tries: 2 }] },
  full_suite: { status: "passed", note: "" }, safety: { flag: true, files: ["steps/merge/run.py"] },
  files: [
    { path: "a.txt", added: 1, removed: 1, binary: false, safety: false, diff: "diff --git a/a.txt b/a.txt\n@@ -1 +1 @@\n-old\n+new\n" },
    { path: "steps/merge/run.py", added: 2, removed: 0, binary: false, safety: true, diff: "" },
  ],
  added: 3, removed: 1, merge_request: "https://github.com/x/y/pull/7",
}

const routes = {
  "GET /api/gates/r.1/review": review,
  "POST /api/gates/r.1/answer": { gate: "r.1", action: "approve", note: "", who: "alex", at: "" },
}

describe("MergeReview", () => {
  it("shows the summary, facts and changed files with diffs", async () => {
    mockApi(routes)
    renderWithProviders(<MergeReview gate={gate} />)
    expect(await screen.findByText("Adds a thing.")).toBeInTheDocument()
    expect(screen.getByText("3 of 4 passed")).toBeInTheDocument()
    expect(screen.getByText("task 3 needed a retry")).toBeInTheDocument()
    expect(screen.getByText("Changes safety code")).toBeInTheDocument()
    expect(screen.getByText("Changed files (2)")).toBeInTheDocument()
    expect(document.querySelector(".tag.t-safety")).not.toBeNull()
    expect(screen.getByText("new").className).toBe("a")
    expect(screen.getByText("old").className).toBe("d")
    expect(screen.getByRole("link", { name: /Merge request on GitHub/ })).toHaveAttribute("href", review.merge_request)
  })

  it("Approve & merge posts approve and shows Merged into main", async () => {
    const { calls } = mockApi(routes)
    renderWithProviders(<MergeReview gate={gate} />)
    fireEvent.click(await screen.findByRole("button", { name: "Approve & merge" }))
    expect(await screen.findByText("Merged into main")).toBeInTheDocument()
    expect(JSON.stringify(calls)).toContain("approve")
  })

  it("Send back needs a note and posts it", async () => {
    const { calls } = mockApi({ ...routes, "POST /api/gates/r.1/answer": { gate: "r.1", action: "back", note: "x", who: "alex", at: "" } })
    renderWithProviders(<MergeReview gate={gate} />)
    fireEvent.click(await screen.findByRole("button", { name: "Send back" }))
    const send = screen.getByRole("button", { name: "Send back note" })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Note for the builder"), { target: { value: "Add a test" } })
    fireEvent.click(send)
    await waitFor(() => expect(JSON.stringify(calls)).toContain("Add a test"))
  })

  it("Don't merge asks first, then skips", async () => {
    const { calls } = mockApi(routes)
    renderWithProviders(<MergeReview gate={gate} />)
    fireEvent.click(await screen.findByRole("button", { name: "Don't merge" }))
    const buttons = await screen.findAllByRole("button", { name: "Don't merge" })
    fireEvent.click(buttons[buttons.length - 1]!)
    await waitFor(() => expect(JSON.stringify(calls)).toContain("skip"))
  })
})
